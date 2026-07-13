from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User


class AuthService:

    @staticmethod
    def register(db: Session, email: str, password: str) -> Optional[User]:
        """Create a new user, or return None if the email is already taken."""
        email = email.strip().lower()  # normalize so Email == email == EMAIL

        existing = db.query(User).filter(User.email == email).first()
        if existing is not None:
            return None

        user = User(email=email, hashed_password=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate(db: Session, email: str, password: str) -> Optional[User]:
        """Return the user if email+password are correct, else None.

        We do the same work whether or not the email exists (look up, then
        verify) so an attacker can't tell "email not found" from "wrong
        password" — both just fail.
        """
        email = email.strip().lower()

        user = db.query(User).filter(User.email == email).first()
        if user is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
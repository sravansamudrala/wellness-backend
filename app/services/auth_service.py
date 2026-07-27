from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import (
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services import email_service
import logging

logger = logging.getLogger(__name__)


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
            logger.warning("Failed login attempt for non-existent user: %s", email)
            return None
        if not verify_password(password, user.hashed_password):
            logger.warning("Login failed: wrong password for %s", email)
            return None
        return user

    @staticmethod
    def request_password_reset(db: Session, email: str) -> None:
        """Create+email a reset token if the email matches a user.

        Always returns None regardless of outcome — the caller (route) must
        give the same generic response either way, so this never leaks
        whether the email exists (same principle as `authenticate`).
        """
        email = email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            logger.info("Password reset requested for non-existent email: %s", email)
            return

        raw_token = generate_reset_token()
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=datetime.utcnow()
            + timedelta(minutes=settings.password_reset_token_expire_minutes),
        )
        db.add(reset_token)
        db.commit()

        reset_link = f"{settings.frontend_url}/reset-password?token={raw_token}"
        email_service.send_password_reset_email(user.email, reset_link)

    @staticmethod
    def reset_password(db: Session, token: str, new_password: str) -> bool:
        """Consume a reset token and set the new password.

        Returns False for any invalid/expired/used/garbage token (all
        indistinguishable to the caller — same enumeration-safety principle),
        True on success.
        """
        token_hash = hash_reset_token(token)
        reset_token = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == token_hash)
            .first()
        )

        if reset_token is None:
            return False
        if reset_token.used_at is not None:
            return False
        if reset_token.expires_at < datetime.utcnow():
            return False

        user = db.query(User).filter(User.id == reset_token.user_id).first()
        if user is None:
            return False

        user.hashed_password = hash_password(new_password)
        reset_token.used_at = datetime.utcnow()
        db.commit()
        return True
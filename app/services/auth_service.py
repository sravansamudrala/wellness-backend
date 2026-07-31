from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
from sqlalchemy import or_
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


def _normalize(s: str) -> str:
    """Strip+lowercase so storage and every lookup compare identically —
    applied to both email and username, everywhere either touches the DB."""
    return s.strip().lower()


class AuthService:

    @staticmethod
    def register(
        db: Session, email: str, password: str, username: Optional[str] = None
    ) -> User:
        """Create a new user.

        Raises ValueError("email_taken") / ValueError("username_taken") if
        either is already in use, so the caller can report which one.
        """
        email = _normalize(email)

        if db.query(User).filter(User.email == email).first() is not None:
            raise ValueError("email_taken")

        normalized_username = _normalize(username) if username else None
        if normalized_username is not None:
            existing_username = (
                db.query(User).filter(User.username == normalized_username).first()
            )
            if existing_username is not None:
                raise ValueError("username_taken")

        user = User(
            email=email,
            username=normalized_username,
            hashed_password=hash_password(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate(db: Session, identifier: str, password: str) -> Optional[User]:
        """Return the user if identifier (email or username) + password are
        correct, else None.

        We do the same work whether or not the identifier exists (look up,
        then verify) so an attacker can't tell "not found" from "wrong
        password" — both just fail.
        """
        identifier = _normalize(identifier)

        user = (
            db.query(User)
            .filter(or_(User.email == identifier, User.username == identifier))
            .first()
        )
        if user is None:
            logger.warning("Failed login attempt for non-existent user: %s", identifier)
            return None
        if not verify_password(password, user.hashed_password):
            logger.warning("Login failed: wrong password for %s", identifier)
            return None
        return user

    @staticmethod
    def update_profile(
        db: Session,
        user_id: UUID,
        username: Optional[str] = None,
        email: Optional[str] = None,
    ) -> User:
        """Update the current user's username and/or email.

        Raises ValueError("username_taken") / ValueError("email_taken") if
        either value belongs to a *different* user.
        """
        user = db.query(User).filter(User.id == user_id).first()

        if username is not None:
            normalized_username = _normalize(username)
            conflict = (
                db.query(User)
                .filter(User.username == normalized_username, User.id != user_id)
                .first()
            )
            if conflict is not None:
                raise ValueError("username_taken")
            user.username = normalized_username

        if email is not None:
            normalized_email = _normalize(email)
            conflict = (
                db.query(User)
                .filter(User.email == normalized_email, User.id != user_id)
                .first()
            )
            if conflict is not None:
                raise ValueError("email_taken")
            user.email = normalized_email

        db.commit()
        db.refresh(user)
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
        # Invalidates every token minted before this point — see the `ver`
        # claim in security.create_access_token and the comparison in
        # api.deps.get_current_user.
        user.token_version += 1
        reset_token.used_at = datetime.utcnow()
        db.commit()
        return True
"""Shared FastAPI dependencies. `get_current_user` turns the incoming
Authorization: Bearer <token> header into a verified user id.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token_claims
from app.database.session import SessionLocal
from app.models.user import User

# Extracts the "Authorization: Bearer <token>" header. auto_error=False means
# it returns None (instead of raising its own 403) when the header is missing,
# so we can raise our own consistent 401 below.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UUID:
    """Return the user id from a valid JWT, or raise 401.

    Any endpoint that adds `user_id: UUID = Depends(get_current_user)` is now
    login-protected: no valid token → FastAPI returns 401 and the endpoint body
    never executes.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token_claims(credentials.credentials)
    if payload is None or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = UUID(payload["sub"])
    # Missing `ver` means a token minted before this feature shipped — treat
    # it as version 0 so existing sessions survive the deploy; they're only
    # invalidated the next time this user actually resets their password.
    token_version = payload.get("ver", 0)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()

    if user is None or user.token_version != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id

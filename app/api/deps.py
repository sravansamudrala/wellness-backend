"""Shared FastAPI dependencies. `get_current_user` turns the incoming
Authorization: Bearer <token> header into a verified user id.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token

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

    user_id = decode_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UUID(user_id)

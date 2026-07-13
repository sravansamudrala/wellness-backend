"""Auth primitives: password hashing (bcrypt) and JWT create/verify (PyJWT).

Kept dependency-free of FastAPI so it's easy to unit-test and reuse.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt  # the PyJWT package imports as `jwt`

from app.core.config import settings


# ----- Passwords -----

def hash_password(password: str) -> str:
    """Return a salted bcrypt hash of `password` (safe to store in the DB).

    `gensalt()` generates a fresh random salt each call, so the same password
    hashes differently every time. The salt is stored *inside* the returned
    hash string, so `verify_password` can read it back out.
    """
    # bcrypt works on bytes, not str, so we encode/decode around it.
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash.

    bcrypt re-derives the salt from `hashed`, hashes `password` with it, and
    compares — in constant time, so it doesn't leak timing information.
    """
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ----- JWTs -----

def create_access_token(user_id: str) -> str:
    """Build a signed JWT whose `sub` (subject) claim is the user id.

    `exp` is a standard claim PyJWT understands: once past it, `decode` raises
    ExpiredSignatureError and the token is rejected.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[str]:
    """Verify a JWT's signature + expiry and return its `sub` (user id).

    Returns None on any problem (bad signature, expired, malformed) — the
    caller turns that into a 401. We never trust the payload without the
    signature check that `jwt.decode` performs here using our secret.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
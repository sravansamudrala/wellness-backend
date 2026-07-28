"""Auth primitives: password hashing (bcrypt) and JWT create/verify (PyJWT).

Kept dependency-free of FastAPI so it's easy to unit-test and reuse.
"""

import hashlib
import secrets
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

    rounds=10 (default would be 12): bcrypt's cost factor is exponential —
    each +1 round roughly doubles the CPU time. 12 rounds takes ~2.6s on
    Render's weak free-tier CPU (measured), which made every login/register
    painfully slow. 10 is still within OWASP's recommended floor.
    """
    # bcrypt works on bytes, not str, so we encode/decode around it.
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10))
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash.

    bcrypt re-derives the salt from `hashed`, hashes `password` with it, and
    compares — in constant time, so it doesn't leak timing information.
    """
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ----- JWTs -----

def create_access_token(user_id: str, token_version: int) -> str:
    """Build a signed JWT whose `sub` (subject) claim is the user id.

    `exp` is a standard claim PyJWT understands: once past it, `decode` raises
    ExpiredSignatureError and the token is rejected.

    `ver` is `token_version` from the users row at the moment this token was
    minted — `get_current_user` compares it against the user's *current*
    token_version on every request. `AuthService.reset_password` bumps that
    column, which makes every token minted before the reset carry a stale
    `ver` and fail that comparison — this is how a stolen session gets
    invalidated even though JWTs are otherwise stateless.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "ver": token_version, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_payload(token: str) -> Optional[dict]:
    """Verify a JWT's signature + expiry and return its full payload.

    Returns None on any problem (bad signature, expired, malformed) — callers
    turn that into a 401. We never trust the payload without the signature
    check that `jwt.decode` performs here using our secret.
    """
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None


def decode_token(token: str) -> Optional[str]:
    """Verify a JWT and return just its `sub` (user id) — kept for callers
    that only need the user id, not the full claim set."""
    payload = _decode_payload(token)
    return payload.get("sub") if payload else None


def decode_token_claims(token: str) -> Optional[dict]:
    """Verify a JWT and return its full claim set (`sub` + `ver`, etc.) — for
    callers (namely `get_current_user`) that need more than just the user id.
    """
    return _decode_payload(token)


# ----- Password reset tokens -----

def generate_reset_token() -> str:
    """A high-entropy, URL-safe raw token to email to the user.

    This is emailed as-is (in the reset link) and never stored raw — only its
    hash (see hash_reset_token) is kept in the DB.
    """
    return secrets.token_urlsafe(32)


def hash_reset_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw reset token, for DB storage/lookup.

    Unlike bcrypt for passwords, a fast deterministic hash is fine here: the
    token is already 256 bits of secure randomness, so it doesn't need a slow
    work factor — we just need a stable digest to look up by.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
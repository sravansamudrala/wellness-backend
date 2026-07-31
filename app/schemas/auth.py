import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

# Deliberately disjoint from a valid email shape (no "@") so a username can
# never collide with an email value — see AuthService.authenticate, which
# looks a single `identifier` up against both columns in one query.
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


def _validate_username(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if not _USERNAME_PATTERN.match(v):
        raise ValueError(
            "Username must be 3-20 characters and contain only letters, "
            "numbers, and underscores."
        )
    return v


class RegisterRequest(BaseModel):
    email: str
    password: str
    username: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _email_must_look_like_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Please enter a valid email address.")
        return v

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: Optional[str]) -> Optional[str]:
        return _validate_username(v)


class LoginRequest(BaseModel):
    identifier: str
    password: str

    # Cheap backward-compat shim: an old frontend build sending {email,
    # password} still works if it lands after the backend deploys but before
    # the frontend does. Safe to remove once both sides are confirmed live.
    @model_validator(mode="before")
    @classmethod
    def _alias_legacy_email(cls, data):
        if isinstance(data, dict) and "identifier" not in data and "email" in data:
            data = {**data, "identifier": data["email"]}
        return data


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    username: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class UpdateMeRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _email_must_look_like_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "@" not in v:
            raise ValueError("Please enter a valid email address.")
        return v

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: Optional[str]) -> Optional[str]:
        return _validate_username(v)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MessageResponse(BaseModel):
    message: str
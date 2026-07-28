from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import create_access_token
from app.database.session import SessionLocal
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService
from fastapi import Request
from app.core.rate_limit import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.post("/register", response_model=TokenResponse)
@limiter.limit(settings.auth_rate_limit)
def register(payload: RegisterRequest, request: Request):
    db: Session = SessionLocal()

    try:
        # Minimal password rule. (bcrypt also caps input at 72 bytes.)
        if len(payload.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters.",
            )

        user = AuthService.register(db, payload.email, payload.password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That email is already registered.",
            )

        # Registration logs you straight in by returning a token.
        return TokenResponse(
            access_token=create_access_token(user.id, user.token_version)
        )
    finally:
        db.close()


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.auth_rate_limit)
def login(payload: LoginRequest, request: Request):
    db: Session = SessionLocal()

    try:
        user = AuthService.authenticate(db, payload.email, payload.password)
        if user is None:
            # One generic message for both "no such email" and "wrong
            # password" — don't reveal which emails exist.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            )

        return TokenResponse(
            access_token=create_access_token(user.id, user.token_version)
        )
    finally:
        db.close()


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit(settings.password_reset_rate_limit)
def forgot_password(payload: ForgotPasswordRequest, request: Request):
    db: Session = SessionLocal()

    try:
        AuthService.request_password_reset(db, payload.email)
        # Always the same response — existence of the email is never revealed.
        return MessageResponse(
            message="If that email is registered, we've sent a password reset link."
        )
    finally:
        db.close()


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit(settings.auth_rate_limit)
def reset_password(payload: ResetPasswordRequest, request: Request):
    db: Session = SessionLocal()

    try:
        if len(payload.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters.",
            )

        ok = AuthService.reset_password(db, payload.token, payload.new_password)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This reset link is invalid or has expired.",
            )
        return MessageResponse(message="Password updated. You can log in now.")
    finally:
        db.close()


@router.get("/me", response_model=UserResponse)
def me(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        return user
    finally:
        db.close()
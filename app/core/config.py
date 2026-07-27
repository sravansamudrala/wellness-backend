from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    # Log every SQL statement (noisy — keep off in production).
    sql_echo: bool = False

    # App-level logging (auth events, push dispatch results, etc).
    log_level: str = "INFO"

    # Web Push (VAPID). Generate a keypair once and set these in the env.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Shared secret guarding the reminder-dispatch endpoint (the cron caller).
    dispatch_token: str = ""

    # IANA timezone the reminder times are expressed in (Render runs UTC).
    reminder_timezone: str = "UTC"

    # Auth: secret used to sign/verify JWTs. REQUIRED (no default) — a hardcoded
    # fallback would let anyone forge tokens. Set JWT_SECRET in .env / Render.
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    # 30 days — this is a casual PWA, so keep users logged in a long time.
    access_token_expire_minutes: int = 43200

    # slowapi rate-limit string for /register and /login, e.g. "5/minute".
    auth_rate_limit: str = "10/minute"

    # Gmail SMTP account used to send password-reset emails (no domain
    # available for a provider like Resend/SendGrid, so we send via a
    # dedicated Gmail account + App Password instead).
    gmail_address: str = ""
    gmail_app_password: str = ""

    # Frontend origin used to build the password-reset link in the email.
    frontend_url: str = "http://localhost:5173"

    # How long a password-reset token stays valid after being issued.
    password_reset_token_expire_minutes: int = 45

    # slowapi rate-limit string for /forgot-password — stricter than
    # auth_rate_limit since this endpoint can be used to spam a stranger's inbox.
    password_reset_rate_limit: str = "3/hour"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
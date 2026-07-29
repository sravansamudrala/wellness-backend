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

    # SendGrid (HTTP API) used to send password-reset emails. Render blocks
    # outbound SMTP entirely, so a plain SMTP client (e.g. Gmail SMTP) can't
    # work there — SendGrid's API is a normal HTTPS call instead. `mail_from`
    # must be verified as a Single Sender in the SendGrid dashboard (no
    # domain needed) before sends will succeed.
    sendgrid_api_key: str = ""
    mail_from: str = ""

    # Frontend origin used to build the password-reset link in the email.
    frontend_url: str = "http://localhost:5173"

    # How long a password-reset token stays valid after being issued.
    password_reset_token_expire_minutes: int = 45

    # slowapi rate-limit string for /forgot-password — stricter than
    # auth_rate_limit since this endpoint can be used to spam a stranger's inbox.
    password_reset_rate_limit: str = "3/hour"

    # Swagger UI (/docs) and ReDoc (/redoc) expose the full API schema to
    # anyone who requests it. Default on for local dev convenience — set
    # ENABLE_API_DOCS=false in Render's production env to hide them.
    enable_api_docs: bool = True

    # Groq's free-tier chat-completions API powers AI-generated encouragement
    # messages (skincare/water streaks, water hydration level). No key set →
    # falls back to the old rule-based messages, app still works either way.
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
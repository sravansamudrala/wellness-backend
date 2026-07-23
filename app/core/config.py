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
    auth_rate_limit: str = "5/minute"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
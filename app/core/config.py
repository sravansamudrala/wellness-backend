from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    # Log every SQL statement (noisy — keep off in production).
    sql_echo: bool = False

    # Web Push (VAPID). Generate a keypair once and set these in the env.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Shared secret guarding the reminder-dispatch endpoint (the cron caller).
    dispatch_token: str = ""

    # IANA timezone the reminder times are expressed in (Render runs UTC).
    reminder_timezone: str = "UTC"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
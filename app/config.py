from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All secrets come from the environment (or a local .env). Never hardcode."""

    mongodb_uri: str
    shortcut_api_key: str
    mongodb_db: str = "expenses"
    mongodb_collection: str = "expenses"
    # extra people, format "Name:key,Name2:key2" (generate keys the same way as
    # SHORTCUT_API_KEY). The main key's user is named via DEFAULT_USER.
    expense_users: str = ""
    default_user: str = "Me"
    
    # Production vs Development settings
    environment: str = "development"  # "production" or "development"
    frontend_poll_interval_ms: int = 300000  # 5 minutes - aggressive polling to prevent sleep (changed from 2 minutes)
    enable_cronjob_ping: bool = True  # Enable /ping endpoint for cronjob.org wake-ups
    cronjob_ping_interval_minutes: int = 4  # cronjob.org should ping every 4 minutes

    # In-process keep-alive: the app pings its own public URL so Render's
    # free tier never sees 15 idle minutes. Off by default — it only makes
    # sense on a deployed instance, never on a laptop or in tests.
    keepalive_enabled: bool = False
    # Blank on Render: RENDER_EXTERNAL_URL is injected and used instead.
    keepalive_url: str = ""
    keepalive_path: str = "/ping"
    # Must stay under Render's 15-minute spin-down; clamped to 1-14.
    keepalive_interval_minutes: float = 10.0
    # Comma-separated browser origins allowed to call this API. Set this to
    # the URL(s) where the standalone dashboard is deployed.
    cors_origins: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # raises at import time if MONGODB_URI / SHORTCUT_API_KEY are missing


def cors_origins() -> list[str]:
    """Return configured frontend origins, ignoring empty values."""
    return [origin.strip().rstrip("/") for origin in settings.cors_origins.split(",") if origin.strip()]


def all_users() -> dict[str, str]:
    """Map of api key -> display name. The primary key first."""
    users = {settings.shortcut_api_key: settings.default_user}
    for pair in settings.expense_users.split(","):
        name, sep, key = pair.partition(":")
        if sep and name.strip() and key.strip():
            users.setdefault(key.strip(), name.strip())
    return users

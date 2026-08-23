from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All secrets come from the environment (or a local .env). Never hardcode."""

    mongodb_uri: str
    shortcut_api_key: str
    mongodb_db: str = "expenses"
    mongodb_collection: str = "expenses"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # raises at import time if MONGODB_URI / SHORTCUT_API_KEY are missing

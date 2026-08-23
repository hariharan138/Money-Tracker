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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # raises at import time if MONGODB_URI / SHORTCUT_API_KEY are missing


def all_users() -> dict[str, str]:
    """Map of api key -> display name. The primary key first."""
    users = {settings.shortcut_api_key: settings.default_user}
    for pair in settings.expense_users.split(","):
        name, sep, key = pair.partition(":")
        if sep and name.strip() and key.strip():
            users.setdefault(key.strip(), name.strip())
    return users

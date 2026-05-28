"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    The starter repo intentionally reads from environment variables only.
    Local developers may copy `.env.example` to `.env`, but real secrets should
    never be committed.
    """

    database_url: str = ""
    openai_api_key: str = ""
    email_api_key: str = ""
    log_level: str = "INFO"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    """Return application settings."""

    return Settings()

"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceSettings(BaseModel):
    """Source-related runtime settings."""

    approved_jobs_path: Path = Path("docs/examples/approved_jobs.sample.json")


class SecretSettings(BaseModel):
    """Secret-bearing settings grouped for dependency injection."""

    database_url: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    email_api_key: SecretStr = SecretStr("")


class Settings(BaseSettings):
    """Runtime settings.

    The starter repo intentionally reads from environment variables only.
    Local developers may copy `.env.example` to `.env`, but real secrets should
    never be committed.
    """

    database_url: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    email_api_key: SecretStr = SecretStr("")
    approved_jobs_path: Path = Path("docs/examples/approved_jobs.sample.json")
    log_level: str = "INFO"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sources(self) -> SourceSettings:
        """Return grouped source settings."""

        return SourceSettings(approved_jobs_path=self.approved_jobs_path)

    @property
    def secrets(self) -> SecretSettings:
        """Return grouped secret settings with masked string representations."""

        return SecretSettings(
            database_url=self.database_url,
            openai_api_key=self.openai_api_key,
            email_api_key=self.email_api_key,
        )


def get_settings() -> Settings:
    """Return application settings."""

    return Settings()

"""Database URL resolution from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL and embedding settings loaded from the environment."""

    database_url: SecretStr = SecretStr("")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "hope_jobs"
    postgres_user: str = "hope_user"
    postgres_password: SecretStr = SecretStr("hope_password")
    embedding_dimension: int = Field(default=768, ge=1)
    embedding_model: str = "google/embeddinggemma-300m"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Return cached database settings."""

    return DatabaseSettings()


def build_postgres_url(settings: DatabaseSettings | None = None) -> str:
    """Assemble a psycopg v3 SQLAlchemy URL from discrete POSTGRES_* parts."""

    resolved = settings or get_database_settings()
    user = quote_plus(resolved.postgres_user)
    password = quote_plus(resolved.postgres_password.get_secret_value())
    host = resolved.postgres_host
    port = resolved.postgres_port
    db = resolved.postgres_db
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _normalize_postgres_url(url: str) -> str:
    """Ensure PostgreSQL URLs use the psycopg v3 driver."""

    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def resolve_database_url(
    database_url: str | None = None,
    *,
    storage: str = "auto",
) -> str:
    """Resolve the persistence target URL for the requested storage mode.

    ``storage`` values:

    * ``auto`` — use ``database_url`` when provided/non-empty, else ``DATABASE_URL``,
      else local SQLite at ``data/hope_job_agent.sqlite3``.
    * ``sqlite`` — force SQLite (empty -> default file path).
    * ``memory`` — ephemeral SQLite in-memory database.
    * ``postgres`` — require a PostgreSQL URL (explicit or assembled from POSTGRES_*).
    """

    mode = storage.strip().casefold()
    explicit = (database_url or "").strip()
    env_url = get_database_settings().database_url.get_secret_value().strip()
    candidate = explicit or env_url

    if mode == "memory":
        return "sqlite:///:memory:"

    if mode == "sqlite":
        if candidate.startswith("sqlite"):
            return candidate
        return ""

    if mode == "postgres":
        if candidate and _is_postgres_url(candidate):
            return _normalize_postgres_url(candidate)
        assembled = build_postgres_url()
        if assembled:
            return assembled
        raise ValueError(
            "PostgreSQL storage requires DATABASE_URL or POSTGRES_* environment "
            "variables."
        )

    # auto
    if candidate:
        return _normalize_postgres_url(candidate)
    return ""


def _is_postgres_url(url: str) -> bool:
    scheme = url.split("://", 1)[0].casefold()
    return scheme.startswith("postgres")


def mask_database_url(url: str) -> str:
    """Return a log-safe database URL with credentials redacted."""

    if "@" not in url or "://" not in url:
        return url
    scheme, remainder = url.split("://", 1)
    if "@" not in remainder:
        return url
    _, host_part = remainder.rsplit("@", 1)
    return f"{scheme}://***:***@{host_part}"


def embedding_dimension() -> int:
    """Return configured embedding vector dimension."""

    env_value = os.getenv("EMBEDDING_DIMENSION")
    if env_value:
        return int(env_value)
    return get_database_settings().embedding_dimension

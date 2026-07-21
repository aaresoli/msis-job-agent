"""Settings for the student platform and private service integrations."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    """Runtime configuration with secure, local-first defaults."""

    app_base_url: str = "http://localhost:3000"
    environment: str = "development"
    allowed_email_domains: list[str] = Field(default_factory=list)
    session_cookie_name: str = "hope_session"
    session_ttl_days: int = 30
    magic_link_ttl_minutes: int = 15
    magic_link_rate_limit_per_hour: int = 5
    invite_only: bool = True
    auth_pepper: SecretStr = SecretStr("development-only-change-me")
    internal_service_token: SecretStr = SecretStr("development-only-change-me")
    apify_webhook_secret: SecretStr = SecretStr("")
    source_approval_id: str = ""
    langgraph_database_url: SecretStr = SecretStr("")
    langgraph_checkpoint_ttl_days: int = 90
    ollama_base_url: str = ""
    ollama_chat_model: str = ""
    # Serves the streaming coach, where a student is watching tokens arrive. An
    # empty value falls back to ollama_chat_model, so a single-model deployment
    # needs no extra configuration.
    ollama_interactive_model: str = ""
    ollama_embedding_model: str = "embeddinggemma"
    # Ollama silently truncates a prompt that exceeds the context window rather
    # than erroring. Market Pulse and resume parsing both send ~30k characters,
    # so the window is set explicitly instead of inherited from the model
    # default. 0 keeps the model default.
    ollama_num_ctx: int = 32768
    # A 120B-class model on a long enrichment prompt does not answer in 60s.
    ollama_timeout_seconds: float = 300.0
    # Sent per request so residency does not depend on how the server was
    # launched. Mirrors the OLLAMA_KEEP_ALIVE compose default.
    ollama_keep_alive: str = "2h"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("hope_minio")
    minio_secret_key: SecretStr = SecretStr("development-only-change-me")
    minio_bucket: str = "hope-private-documents"
    minio_secure: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "HOPE Career Intelligence <no-reply@example.edu>"
    csrf_header_name: str = "X-CSRF-Token"
    aggregate_minimum_count: int = 5
    ai_trace_retention_days: int = 30
    otel_exporter_otlp_endpoint: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> PlatformSettings:
        if self.environment.casefold() != "production":
            return self
        unsafe = "development-only-change-me"
        if unsafe in {
            self.auth_pepper.get_secret_value(),
            self.internal_service_token.get_secret_value(),
            self.minio_secret_key.get_secret_value(),
        }:
            raise ValueError("Production requires unique platform secrets")
        if not self.app_base_url.startswith("https://"):
            raise ValueError("Production APP_BASE_URL must use HTTPS")
        return self


@lru_cache
def get_platform_settings() -> PlatformSettings:
    return PlatformSettings()

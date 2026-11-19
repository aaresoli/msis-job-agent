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
    # OpenAI-compatible vLLM chat endpoint. Empty disables local AI and the
    # graphs degrade to review/deterministic fallbacks.
    vllm_base_url: str = ""
    vllm_chat_model: str = ""
    # Embeddings use Hugging Face TEI rather than sharing the chat server.
    # Keeping this provider-neutral also makes an embedding backend swap
    # independent from vLLM.
    embedding_base_url: str = ""
    embedding_model: str = "google/embeddinggemma-300m"
    # Server --max-model-len. Used client-side only to warn before a prompt is
    # likely to be rejected. 0 disables the warning.
    vllm_max_model_len: int = 16384
    # Completion budget. Enrichment JSON is short; coach replies need room.
    vllm_max_tokens: int = 2048
    vllm_interactive_max_tokens: int = 1024
    # gpt-oss always reasons; the only choice is how much. Empty leaves the
    # server default. Mapped to OpenAI ``reasoning_effort`` for vLLM's
    # openai_gptoss parser.
    #
    # The batch value is deliberately NOT "low": measured over 40 real
    # postings under Ollama, "low" cut enrichment from 17.2s to 9.4s each but
    # dropped schema acceptance from 36/40 to 33/40. Staff review time is
    # scarcer than GPU time here, so the default keeps the quality.
    vllm_batch_reasoning: str = ""
    vllm_interactive_reasoning: str = "medium"
    # Application-side batch fan-out. The server may keep more decode slots
    # than this so an interactive request can enter immediately.
    vllm_batch_concurrency: int = 4
    # vLLM schedules lower numeric values first. Coach traffic stays ahead of
    # enrichment without needing a second copy of the 120B model.
    vllm_batch_priority: int = 0
    vllm_interactive_priority: int = -10
    # A 120B-class model on a long enrichment prompt does not answer in 60s.
    vllm_timeout_seconds: float = 300.0
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("hope_minio")
    minio_secret_key: SecretStr = SecretStr("development-only-change-me")
    minio_bucket: str = "hope-private-documents"
    minio_secure: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    # Local mail catchers (Mailpit) speak plain SMTP and do not advertise
    # STARTTLS, which smtplib turns into SMTPNotSupportedError. Opting out is
    # explicit rather than an automatic downgrade, so a real relay that stops
    # offering TLS fails loudly instead of silently sending links in the clear.
    smtp_starttls: bool = True
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "HOPE Career Intelligence <no-reply@example.edu>"
    # Backups land in their own bucket, not minio_bucket: that one holds
    # student resumes and is purged per user by the retention task, which must
    # never be able to reach a backup.
    backup_bucket: str = "hope-backups"
    backup_retention_days: int = 30
    # A relay attempt that has failed this many times is not going to start
    # working; it is dead-lettered so the backlog gauge measures real work
    # rather than one poisoned row retried forever.
    outbox_max_attempts: int = 5
    outbox_batch_size: int = 100
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

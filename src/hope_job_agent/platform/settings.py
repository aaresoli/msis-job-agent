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
    ollama_num_ctx: int = 16384
    # The coach prompt is a question plus retrieved context, never the 30k-char
    # payloads the batch graphs send. Every slot's KV cache is sized from this,
    # so giving the interactive model its own smaller window buys back memory
    # that ollama_num_parallel then spends on concurrency. 0 inherits
    # ollama_num_ctx.
    ollama_interactive_num_ctx: int = 8192
    # gpt-oss always reasons; the only choice is how much. Empty leaves the
    # model's own default.
    #
    # The batch value is deliberately NOT "low", even though the reasoning
    # tokens are discarded (chat() returns message.content and never reads
    # message.thinking) and lowering it is the single largest throughput win
    # available. Measured over 40 real postings, "low" cut enrichment from
    # 17.2s to 9.4s each but dropped schema acceptance from 36/40 to 33/40 --
    # three more postings per forty landing in a human review queue. The
    # committed gold set does not show this: its postings are short summaries
    # and score 12/12 either way. Staff review time is scarcer than GPU time
    # here, so the default keeps the quality.
    ollama_batch_reasoning: str = ""
    ollama_interactive_reasoning: str = "medium"
    # Must match OLLAMA_NUM_PARALLEL on the server. The workers use it to size
    # their own fan-out: more in-flight requests than the server has slots just
    # queues inside Ollama, where nothing can observe the wait.
    ollama_num_parallel: int = 4
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

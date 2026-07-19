"""Disabled Denodo connector contract, ready for the approved view mapping."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.contracts import SourceBatch, SourceDisabledError


class DenodoConfig(BaseModel):
    enabled: bool = False
    base_url: str = ""
    auth_method: Literal["bearer", "basic", "oauth2"] = "bearer"
    credential: SecretStr = SecretStr("")
    view_name: str = ""
    field_mapping: dict[str, str] = Field(default_factory=dict)
    page_size: int = Field(default=100, ge=1, le=1000)
    retry_attempts: int = Field(default=3, ge=0, le=10)


class DenodoConnector:
    source_name = "ksbit_denodo"

    def __init__(self, config: DenodoConfig) -> None:
        self.config = config
        self.enabled = config.enabled

    def fetch_page(
        self,
        *,
        cursor: str | None = None,
        watermark: datetime | None = None,
        limit: int = 100,
    ) -> SourceBatch[JobPosting]:
        del cursor, watermark, limit
        if not self.enabled:
            raise SourceDisabledError(
                "Denodo is disabled until its endpoint, credentials, and view "
                "mapping are approved."
            )
        raise SourceDisabledError(
            "Denodo endpoint mapping has not been supplied; no network request "
            "was made."
        )


def map_denodo_record(record: dict[str, Any], mapping: dict[str, str]) -> JobPosting:
    def value(name: str, default: Any = None) -> Any:
        source_field = mapping.get(name, name)
        return record.get(source_field, default)

    return JobPosting(
        source="ksbit_denodo",
        source_job_id=str(value("source_job_id")),
        title=str(value("title", "")),
        company=str(value("company", "")),
        location=str(value("location", "Not specified")),
        description=str(value("description", "")),
        url=str(value("url", "")),
        posted_date=value("posted_date"),
        employment_type=value("employment_type"),
        raw_metadata={"denodo_record": record},
    )

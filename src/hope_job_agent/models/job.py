"""Job posting model used across ingestion, ranking, and delivery."""

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class JobPosting(BaseModel):
    """Normalized job posting from an approved source."""

    source: str = Field(min_length=1)
    source_job_id: str | None = None
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str = Field(min_length=1)
    description: str = Field(min_length=1)
    url: str = Field(min_length=1)
    posted_date: date | None = None
    employment_type: str | None = None
    seniority: str | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    role_confidence_scores: dict[str, float] = Field(default_factory=dict)
    concentration_confidence_scores: dict[str, float] = Field(default_factory=dict)
    classification_uncertain: bool = False
    opt_cpt_flag: bool | None = None
    # Optional enrichment fields. These stay ``None``/empty for existing
    # local-export sources and are populated by the company_careers source
    # family (ATS-backed employer career pages). They are additive and do not
    # change the required core contract used by KelleyLink/KSBIT ingestion.
    source_detail: str | None = None
    apply_url: str | None = None
    location_type: str | None = None
    department: str | None = None
    application_deadline: date | None = None
    compensation: str | None = None
    career_stage: str | None = None
    relevance_score: float | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Validate URL shape while storing a plain string."""

        return str(_HTTP_URL_ADAPTER.validate_python(value))

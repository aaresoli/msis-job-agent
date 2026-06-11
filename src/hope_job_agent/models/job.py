"""Job posting model used across ingestion, ranking, and delivery."""

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class JobPosting(BaseModel):
    """Normalized job posting from an approved source."""

    source: str = Field(min_length=1)
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
    opt_cpt_flag: bool | None = None
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

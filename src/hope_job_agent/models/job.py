"""Job posting model used across ingestion, ranking, and delivery."""

from datetime import date

from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """Normalized job posting from an approved source."""

    source: str = Field(default=None)
    title: str = Field(default=None)
    company: str = Field(default=None)
    location: str = Field(default=None)
    description: str = Field(default=None)
    url: str = Field(default=None)
    posted_date: date | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    opt_cpt_flag: bool | None = None

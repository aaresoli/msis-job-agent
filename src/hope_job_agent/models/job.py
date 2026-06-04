"""Job posting model used across ingestion, ranking, and delivery."""

from datetime import date

from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """Normalized job posting from an approved source."""

    source: str
    title: str
    company: str
    location: str
    description: str
    seniority: str
    url: str
    posted_date: date | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    opt_cpt_flag: bool | None = None

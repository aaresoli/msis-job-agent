"""Models for representing job matches."""

from pydantic import BaseModel, Field

from hope_job_agent.models.job import JobPosting


class JobMatch(BaseModel):
    """A ranked match between a student and a job."""

    job: JobPosting
    score: float
    reasons: list[str] = Field(default_factory=list)

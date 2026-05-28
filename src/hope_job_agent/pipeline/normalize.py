"""Normalization helpers for converting records into shared models."""

from hope_job_agent.models.job import JobPosting


def normalize_job(job: JobPosting) -> JobPosting:
    """Return a normalized job.

    This placeholder accepts an existing `JobPosting`. Future source-specific
    adapters can map raw records into this shared model before validation.
    """

    return job.model_copy(
        update={
            "title": job.title.strip(),
            "company": job.company.strip(),
            "location": job.location.strip(),
            "description": job.description.strip(),
        }
    )

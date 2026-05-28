"""Validation helpers for normalized job postings."""

from hope_job_agent.models.job import JobPosting


def validate_job(job: JobPosting) -> bool:
    """Return whether a job has the minimum fields needed downstream."""

    required_text = [job.source, job.title, job.company, job.location, job.description]
    return all(value.strip() for value in required_text) and bool(job.url)

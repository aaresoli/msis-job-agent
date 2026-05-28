"""Simple placeholder classifier for concentration tags."""

from hope_job_agent.classification.taxonomy import MSIS_CONCENTRATIONS
from hope_job_agent.models.job import JobPosting


def classify_job(job: JobPosting) -> list[str]:
    """Return existing tags that are part of the starter MSIS taxonomy."""

    return [tag for tag in job.concentration_tags if tag in MSIS_CONCENTRATIONS]

"""Ingestion helpers for approved job source adapters."""

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


def ingest_jobs(source: BaseJobSource) -> list[JobPosting]:
    """Fetch jobs from one approved source adapter."""

    return source.fetch_jobs()

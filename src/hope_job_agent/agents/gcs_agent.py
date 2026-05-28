"""Placeholder Graduate Career Services summary agent."""

from collections import Counter

from hope_job_agent.models.job import JobPosting


def summarize_jobs_for_gcs(jobs: list[JobPosting]) -> dict[str, object]:
    """Summarize job volume by source, concentration tag, and company."""

    source_counts = Counter(job.source for job in jobs)
    company_counts = Counter(job.company for job in jobs)
    concentration_counts = Counter(
        tag for job in jobs for tag in job.concentration_tags
    )

    return {
        "total_jobs": len(jobs),
        "sources": dict(source_counts),
        "companies": dict(company_counts),
        "concentrations": dict(concentration_counts),
    }

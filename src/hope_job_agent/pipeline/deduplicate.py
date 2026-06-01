"""Deduplication helpers for normalized job postings."""

from hope_job_agent.models.job import JobPosting


def deduplicate_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    """Remove duplicate jobs by URL while preserving first-seen order."""

    seen_urls: set[str] = set()
    unique_jobs: list[JobPosting] = []
    attributes_to_check = ['title', 'company', 'location']

    for job in jobs:
        normalized_url = str(job.url).rstrip("/").lower()
        if normalized_url in seen_urls:
            continue
        elif any(all(getattr(row, attr).lower() == getattr(job, attr).lower() for attr in attributes_to_check) for row in unique_jobs) == True:
            continue
        seen_urls.add(normalized_url)
        unique_jobs.append(job)

    return unique_jobs

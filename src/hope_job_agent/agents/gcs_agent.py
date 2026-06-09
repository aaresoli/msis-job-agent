"""Placeholder Graduate Career Services summary agent."""

from collections import Counter
from datetime import date

from hope_job_agent.models.job import JobPosting


def summarize_jobs_for_gcs(jobs: list[JobPosting]) -> dict[str, object]:
    """Summarize program-level job trends for Graduate Career Services."""

    source_counts = Counter(job.source for job in jobs)
    company_counts = Counter(job.company for job in jobs)
    role_counts = Counter(tag for job in jobs for tag in job.role_tags)
    concentration_counts = Counter(
        tag for job in jobs for tag in job.concentration_tags
    )
    location_counts = Counter(job.location for job in jobs)
    seniority_counts = Counter(job.seniority or "Unknown" for job in jobs)
    opt_cpt_counts = Counter(_opt_cpt_label(job.opt_cpt_flag) for job in jobs)
    weekly_counts = Counter(_week_bucket(job.posted_date) for job in jobs)

    return {
        "total_jobs": len(jobs),
        "sources": dict(source_counts),
        "companies": dict(company_counts),
        "roles": dict(role_counts),
        "concentrations": dict(concentration_counts),
        "locations": dict(location_counts),
        "seniority": dict(seniority_counts),
        "opt_cpt_signals": dict(opt_cpt_counts),
        "posting_weeks": dict(weekly_counts),
    }


def _opt_cpt_label(value: bool | None) -> str:
    if value is True:
        return "cpt_opt_friendly"
    if value is False:
        return "not_cpt_opt_friendly"
    return "unknown"


def _week_bucket(posted_date: date | None) -> str:
    if posted_date is None:
        return "unknown"
    start_of_week = posted_date.fromordinal(
        posted_date.toordinal() - posted_date.weekday()
    )
    return start_of_week.isoformat()

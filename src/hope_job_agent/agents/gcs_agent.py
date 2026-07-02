"""Graduate Career Services program-level trend summary.

Produces the deterministic trend contract consumed by the GCS dashboard. The
shape aligns with `sql/gcs_trend_queries.sql` (postings, roles, employers, and
locations by concentration, plus OPT/CPT and recency views) so the dashboard
can be built off `*.gcs_trends.json` without re-deriving anything.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime

from hope_job_agent.classification.taxonomy import CONCENTRATION_CODES
from hope_job_agent.models.job import JobPosting

DEFAULT_TOP_N = 10


def summarize_jobs_for_gcs(
    jobs: list[JobPosting],
    *,
    today: date | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, object]:
    """Summarize program-level job trends for Graduate Career Services."""

    reference_date = today or datetime.now(UTC).date()

    source_counts = Counter(job.source for job in jobs)
    company_counts = Counter(job.company for job in jobs)
    role_counts = Counter(tag for job in jobs for tag in job.role_tags)
    concentration_counts = Counter(
        tag for job in jobs for tag in job.concentration_tags
    )
    location_counts = Counter(job.location for job in jobs)
    seniority_counts = Counter(job.seniority or "Unknown" for job in jobs)
    employment_type_counts = Counter((job.employment_type or "Unknown") for job in jobs)
    opt_cpt_counts = Counter(_opt_cpt_label(job.opt_cpt_flag) for job in jobs)
    weekly_counts = Counter(_week_bucket(job.posted_date) for job in jobs)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_date": reference_date.isoformat(),
        "total_jobs": len(jobs),
        # Backward-compatible flat counts.
        "sources": dict(source_counts),
        "companies": dict(company_counts),
        "roles": dict(role_counts),
        "concentrations": dict(concentration_counts),
        "locations": dict(location_counts),
        "seniority": dict(seniority_counts),
        "opt_cpt_signals": dict(opt_cpt_counts),
        "posting_weeks": dict(weekly_counts),
        # Enriched dashboard contract.
        "concentration_codes": {
            tag: CONCENTRATION_CODES.get(tag, tag) for tag in concentration_counts
        },
        "employment_types": _sorted_counts(employment_type_counts),
        "top_employers": _top_items(company_counts, top_n),
        "top_locations": _top_items(location_counts, top_n),
        "roles_by_concentration": _nested_counts(jobs, "role_tags"),
        "opt_cpt_by_concentration": _opt_cpt_by_concentration(jobs),
        "top_employers_by_concentration": _top_nested(
            jobs, lambda job: [job.company], top_n
        ),
        "recency": {
            "last_30_days": _recent_count(jobs, reference_date, 30),
            "last_90_days": _recent_count(jobs, reference_date, 90),
            "missing_posted_date": sum(1 for job in jobs if job.posted_date is None),
        },
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


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _top_items(counter: Counter[str], top_n: int) -> list[dict[str, object]]:
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "count": count} for name, count in ordered[:top_n]]


def _nested_counts(jobs: list[JobPosting], attribute: str) -> dict[str, dict[str, int]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for job in jobs:
        for concentration in job.concentration_tags:
            for value in getattr(job, attribute) or ["Unclassified"]:
                nested[concentration][value] += 1
    return {
        concentration: _sorted_counts(counter)
        for concentration, counter in sorted(nested.items())
    }


def _opt_cpt_by_concentration(jobs: list[JobPosting]) -> dict[str, dict[str, int]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for job in jobs:
        label = _opt_cpt_label(job.opt_cpt_flag)
        for concentration in job.concentration_tags:
            nested[concentration][label] += 1
    return {
        concentration: _sorted_counts(counter)
        for concentration, counter in sorted(nested.items())
    }


def _top_nested(jobs, value_fn, top_n: int) -> dict[str, list[dict[str, object]]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for job in jobs:
        for concentration in job.concentration_tags:
            for value in value_fn(job):
                nested[concentration][value] += 1
    return {
        concentration: _top_items(counter, top_n)
        for concentration, counter in sorted(nested.items())
    }


def _recent_count(jobs: list[JobPosting], reference_date: date, days: int) -> int:
    return sum(
        1
        for job in jobs
        if job.posted_date is not None
        and 0 <= (reference_date - job.posted_date).days <= days
    )

from datetime import UTC, datetime, timedelta

from hope_job_agent.discovery.service import (
    MAX_POSTING_AGE_DAYS,
    JobQuery,
    apply_filters,
)
from hope_job_agent.models.job import JobPosting


def _job(
    job_id: str, *, posted_date=None, location: str = "Chicago, IL"
) -> tuple[str, JobPosting]:
    posting = JobPosting(
        source="company_careers",
        source_job_id=job_id,
        title="Data Analyst",
        company="Acme",
        location=location,
        description="Build SQL dashboards.",
        url=f"https://example.com/jobs/{job_id}",
        posted_date=posted_date,
    )
    return job_id, posting


def test_postings_older_than_a_month_are_hidden():
    today = datetime.now(UTC).date()
    fresh_job = _job("fresh", posted_date=today - timedelta(days=5))
    stale_job = _job(
        "stale", posted_date=today - timedelta(days=MAX_POSTING_AGE_DAYS + 1)
    )

    result = apply_filters([fresh_job, stale_job], JobQuery())

    kept_ids = {job_id for job_id, _ in result}
    assert kept_ids == {"fresh"}


def test_postings_with_unknown_posted_date_stay_visible():
    unknown_job = _job("unknown", posted_date=None)

    result = apply_filters([unknown_job], JobQuery())

    assert [job_id for job_id, _ in result] == ["unknown"]


def test_non_us_postings_are_hidden_regardless_of_source():
    # Covers rows persisted before the ingestion-side filter existed, and
    # rows from sources (LinkedIn, KelleyLink) that never had one.
    us_job = _job("us", location="Chicago, IL")
    foreign_job = _job("foreign", location="Bengaluru, Karnataka, India")

    result = apply_filters([us_job, foreign_job], JobQuery())

    assert [job_id for job_id, _ in result] == ["us"]


def test_unknown_and_unspecified_remote_locations_are_hidden():
    remote_us = _job("remote-us", location="Remote - US")
    remote_unknown = _job("remote", location="Remote")
    unknown = _job("unknown-location", location="Not specified")

    result = apply_filters([remote_us, remote_unknown, unknown], JobQuery())

    assert [job_id for job_id, _ in result] == ["remote-us"]

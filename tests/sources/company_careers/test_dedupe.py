"""Deduplication behavior for company_careers postings.

Exercises the four dedupe signals used by the shared pipeline dedupe against
company_careers-shaped postings: canonical URL, external/source job id,
company+title+location, and content hash.
"""

from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs


def _job(**overrides) -> JobPosting:
    defaults = {
        "source": "company_careers",
        "source_job_id": "greenhouse:acme:1001",
        "title": "Data Analyst Intern",
        "company": "Acme",
        "location": "Indianapolis, IN",
        "description": "Build SQL dashboards in Tableau.",
        "url": "https://boards.greenhouse.io/acme/jobs/1001",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def test_dedupe_by_canonical_url_ignores_tracking_params():
    jobs = [
        _job(),
        _job(url="https://boards.greenhouse.io/acme/jobs/1001/?utm_source=x"),
    ]
    assert len(deduplicate_jobs(jobs)) == 1


def test_dedupe_by_source_job_id_even_with_different_url():
    jobs = [
        _job(),
        _job(url="https://boards.greenhouse.io/acme/jobs/1001-mirror"),
    ]
    assert len(deduplicate_jobs(jobs)) == 1


def test_dedupe_by_content_signature():
    jobs = [
        _job(source_job_id=None, url="https://a.example.com/1"),
        _job(source_job_id=None, url="https://b.example.com/2"),
    ]
    assert len(deduplicate_jobs(jobs)) == 1


def test_keeps_distinct_roles():
    jobs = [
        _job(),
        _job(
            source_job_id="greenhouse:acme:1002",
            title="Security Analyst",
            url="https://boards.greenhouse.io/acme/jobs/1002",
            description="SOC monitoring and incident response.",
        ),
    ]
    assert len(deduplicate_jobs(jobs)) == 2

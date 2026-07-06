from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.greenhouse import (
    GreenhouseProvider,
)

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(
        company_name="Acme", ats_provider="greenhouse", ats_slug="acme"
    )


def test_greenhouse_parses_jobs(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    provider = GreenhouseProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 3
    analyst = jobs[0]
    assert analyst.title == "Data Analyst Intern"
    assert analyst.source_job_id == "1001"
    assert analyst.company == "Acme"
    assert analyst.url == "https://boards.greenhouse.io/acme/jobs/1001"
    assert analyst.department == "Data & Analytics"
    assert "Tableau" in analyst.description  # HTML entities decoded
    assert analyst.posted_date is not None


def test_greenhouse_marks_remote_location_type(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    provider = GreenhouseProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    remote_job = next(job for job in jobs if job.source_job_id == "1002")
    assert remote_job.location_type == "remote"


def test_greenhouse_respects_max_jobs_per_company(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    provider = GreenhouseProvider()

    jobs = provider.fetch(
        make_client(transport), _target(), FetchPolicy(max_jobs_per_company=1)
    )

    assert len(jobs) == 1

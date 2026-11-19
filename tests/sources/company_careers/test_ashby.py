from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.ashby import AshbyProvider

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(company_name="Acme", ats_provider="ashby", ats_slug="acme")


def test_ashby_parses_jobs(transport):
    transport.route(
        method="GET",
        contains="api.ashbyhq.com/posting-api/job-board/acme",
        body=load_fixture("ashby_jobs.json"),
    )
    provider = AshbyProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 2
    security = jobs[0]
    assert security.title == "Security Analyst, Early Career"
    assert security.source_job_id == "ash-3001"
    assert security.url == "https://jobs.ashbyhq.com/acme/3001"
    assert security.apply_url == "https://jobs.ashbyhq.com/acme/3001/application"
    assert security.employment_type == "FullTime"
    assert security.department == "Security"
    assert security.location_type == "remote"
    assert security.compensation == "$80K - $110K"
    assert "incident response" in security.description

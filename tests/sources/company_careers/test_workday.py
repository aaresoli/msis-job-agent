from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.workday import WorkdayProvider

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(
        company_name="Acme",
        ats_provider="workday",
        host="acme.wd12.myworkdayjobs.com",
        tenant="acme",
        site="External_Career_Site",
    )


def test_workday_parses_and_fetches_detail(transport):
    transport.route(
        method="GET",
        contains="/wday/cxs/acme/External_Career_Site/job/Indiana/Solutions-Engineer_JR5001",
        body=load_fixture("workday_detail_JR5001.json"),
    )
    transport.route(
        method="POST",
        contains="/wday/cxs/acme/External_Career_Site/jobs",
        body=load_fixture("workday_jobs.json"),
    )
    provider = WorkdayProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Solutions Engineer, New Grad"
    assert job.source_job_id == "JR5001"
    assert job.location == "Indianapolis, IN"
    assert job.url == (
        "https://acme.wd12.myworkdayjobs.com/External_Career_Site"
        "/job/Indiana/Solutions-Engineer_JR5001"
    )
    assert "enterprise platform" in job.description


def test_workday_requires_tenant_site_host(transport):
    import pytest

    from hope_job_agent.sources.company_careers.providers.base import ProviderError

    provider = WorkdayProvider()
    target = CompanyTarget(company_name="Acme", ats_provider="workday")

    with pytest.raises(ProviderError):
        provider.fetch(make_client(transport), target, FetchPolicy())

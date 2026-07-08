import pytest

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.base import ProviderError
from hope_job_agent.sources.company_careers.providers.oraclecloud import (
    OracleCloudProvider,
)

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(
        company_name="Acme Corp",
        ats_provider="oraclecloud",
        host="acme.fa.us2.oraclecloud.com",
        site="CX_1001",
    )


def test_oraclecloud_parses_and_fetches_detail(transport):
    transport.route(
        method="GET",
        contains="recruitingCEJobRequisitionDetails",
        body=load_fixture("oraclecloud_detail_123456.json"),
    )
    transport.route(
        method="GET",
        contains="recruitingCEJobRequisitions?onlyData",
        body=load_fixture("oraclecloud_requisitions.json"),
    )
    provider = OracleCloudProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id == "123456"
    assert job.title == "Business Systems Analyst"
    assert job.location == "Chicago, IL, United States"
    assert job.location_type == "hybrid"
    assert job.url == (
        "https://acme.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en"
        "/sites/CX_1001/job/123456"
    )
    assert "enterprise platform" in job.description
    assert job.posted_date is not None and job.posted_date.year == 2026


def test_oraclecloud_falls_back_to_short_description(transport):
    transport.route(
        method="GET",
        contains="recruitingCEJobRequisitions?onlyData",
        body=load_fixture("oraclecloud_requisitions.json"),
    )
    provider = OracleCloudProvider()

    jobs = provider.fetch(
        make_client(transport),
        _target(),
        FetchPolicy(fetch_descriptions=False),
    )

    assert len(jobs) == 1
    assert jobs[0].description == "Analyst role on the ERP team."


def test_oraclecloud_requires_host_and_site(transport):
    provider = OracleCloudProvider()
    target = CompanyTarget(company_name="Acme", ats_provider="oraclecloud")

    with pytest.raises(ProviderError):
        provider.fetch(make_client(transport), target, FetchPolicy())


def test_oraclecloud_rejects_non_oracle_host(transport):
    provider = OracleCloudProvider()
    target = CompanyTarget(
        company_name="Acme",
        ats_provider="oraclecloud",
        host="acme.example.com",
        site="CX_1",
    )

    with pytest.raises(ProviderError):
        provider.primary_endpoint(target)

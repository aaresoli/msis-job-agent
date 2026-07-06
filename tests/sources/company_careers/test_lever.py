from datetime import date

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.lever import LeverProvider

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(company_name="Acme", ats_provider="lever", ats_slug="acme")


def test_lever_parses_postings(transport):
    transport.route(
        method="GET",
        contains="api.lever.co/v0/postings/acme",
        body=load_fixture("lever_postings.json"),
    )
    provider = LeverProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 2
    analyst = jobs[0]
    assert analyst.title == "Business Systems Analyst, University Graduate"
    assert analyst.source_job_id == "lev-2001"
    assert analyst.url == "https://jobs.lever.co/acme/2001"
    assert analyst.apply_url == "https://jobs.lever.co/acme/2001/apply"
    assert analyst.employment_type == "Full-time"
    assert analyst.location == "Chicago, IL"
    assert analyst.department == "IT"
    assert analyst.location_type == "hybrid"
    assert analyst.posted_date == date(2026, 6, 10)
    assert "New grad" in analyst.description  # list content appended


def test_lever_non_list_response_raises(transport):
    transport.route(
        method="GET",
        contains="api.lever.co/v0/postings/acme",
        body={"unexpected": True},
    )
    provider = LeverProvider()

    import pytest

    from hope_job_agent.sources.company_careers.providers.base import ProviderError

    with pytest.raises(ProviderError):
        provider.fetch(make_client(transport), _target(), FetchPolicy())

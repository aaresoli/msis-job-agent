from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.smartrecruiters import (
    SmartRecruitersProvider,
)

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(
        company_name="Acme", ats_provider="smartrecruiters", ats_slug="AcmeCorp"
    )


def test_smartrecruiters_parses_and_fetches_detail(transport):
    transport.route(
        method="GET",
        contains="companies/AcmeCorp/postings/sr-4001",
        body=load_fixture("smartrecruiters_detail_4001.json"),
    )
    transport.route(
        method="GET",
        contains="companies/AcmeCorp/postings",
        body=load_fixture("smartrecruiters_postings.json"),
    )
    provider = SmartRecruitersProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 2
    consultant = jobs[0]
    assert consultant.title == "Cloud Solutions Consultant (Associate)"
    assert consultant.source_job_id == "sr-4001"
    assert consultant.url == "https://jobs.smartrecruiters.com/AcmeCorp/sr-4001"
    assert consultant.employment_type == "Full-time"
    assert consultant.department == "Technology Consulting"
    assert consultant.location == "Austin, TX, United States"
    assert consultant.location_type == "hybrid"
    # Detail endpoint description merged in.
    assert "cloud migration" in consultant.description
    assert "Python" in consultant.description


def test_smartrecruiters_skips_detail_when_disabled(transport):
    transport.route(
        method="GET",
        contains="companies/AcmeCorp/postings",
        body=load_fixture("smartrecruiters_postings.json"),
    )
    provider = SmartRecruitersProvider()

    jobs = provider.fetch(
        make_client(transport),
        _target(),
        FetchPolicy(fetch_descriptions=False),
    )

    # Only the list endpoint was requested (no per-posting detail calls).
    detail_calls = [req for req in transport.requests if "/postings/sr-" in req["url"]]
    assert detail_calls == []
    # Provider returns empty description; the adapter supplies a placeholder later.
    assert jobs[0].description == ""

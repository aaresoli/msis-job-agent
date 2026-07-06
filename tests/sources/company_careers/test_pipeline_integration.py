"""End-to-end: company_careers runs through run_mvp independently of Denodo."""

from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline
from hope_job_agent.sources.company_careers.adapter import CompanyCareersSource
from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfig,
    CompanyTarget,
    FetchPolicy,
)
from hope_job_agent.sources.registry import (
    create_source_adapter,
    ensure_source_allowed,
)

from .conftest import load_fixture, make_client

OFFICIAL = {
    "Data Analytics and AI",
    "Cybersecurity and Risk Analytics",
    "Digital Enterprise Systems and AI",
    "Digital Platforms and Security",
    "IS Research",
}


def _source(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    config = CompanyCareersConfig(
        fetch_policy=FetchPolicy(min_interval_seconds=0.0, respect_robots=False),
        companies=[
            CompanyTarget(
                company_name="Acme", ats_provider="greenhouse", ats_slug="acme"
            )
        ],
    )
    return CompanyCareersSource(config=config, client=make_client(transport))


def test_company_careers_registered_and_allowed():
    metadata = ensure_source_allowed("company_careers")
    assert metadata.source_type == "company_careers"


def test_create_source_adapter_builds_company_careers():
    source = create_source_adapter("company_careers", "config/company_careers.yml")
    assert isinstance(source, CompanyCareersSource)
    assert source.source_name == "company_careers"


def test_run_mvp_jobs_only_dry_run(tmp_path, transport):
    source = _source(transport)

    result = run_mvp_pipeline(
        source_name="company_careers",
        output_path=tmp_path / "cc.jobs.json",
        company_source=source,
        dry_run=True,
    )

    summary = result.summary
    assert summary["source"] == "company_careers"
    assert summary["mode"] == "jobs-only"
    assert summary["unique_count"] >= 1
    assert summary["company_careers_health"]["kept_count"] >= 1
    assert summary["company_careers_health"]["per_company"][0]["company_name"] == "Acme"


def test_pipeline_classification_uses_official_concentration_names(transport):
    from hope_job_agent.classification.classifier import classify_job_posting

    source = _source(transport)
    jobs = source.fetch_all_jobs().jobs

    for job in jobs:
        classified = classify_job_posting(job)
        assert set(classified.concentration_tags).issubset(OFFICIAL)

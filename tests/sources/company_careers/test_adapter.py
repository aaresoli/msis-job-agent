from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.company_careers.adapter import CompanyCareersSource
from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfig,
    CompanyTarget,
    FetchPolicy,
)

from .conftest import load_fixture, make_client


def _config(companies, *, respect_robots=False, max_total=2000):
    return CompanyCareersConfig(
        fetch_policy=FetchPolicy(
            min_interval_seconds=0.0,
            backoff_seconds=0.0,
            respect_robots=respect_robots,
            max_total_jobs_per_run=max_total,
        ),
        relevance_threshold=3,
        companies=companies,
    )


def _greenhouse_company(slug="acme"):
    return CompanyTarget(company_name="Acme", ats_provider="greenhouse", ats_slug=slug)


def test_fetch_all_jobs_keeps_only_relevant_and_reports_health(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.raw_count == 3
    assert result.kept_count == 1
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert isinstance(job, JobPosting)
    assert job.source == "company_careers"
    assert job.title == "Data Analyst Intern"
    assert job.source_detail == "greenhouse:acme"
    assert job.relevance_score is not None and job.relevance_score >= 3
    assert job.career_stage == "internship"

    relevance = job.raw_metadata["msis_relevance"]
    assert "Data Analytics and AI" in relevance["concentration_hints"]
    assert job.raw_metadata["provider"] == "greenhouse"
    assert job.raw_metadata["provider_payload"]["id"] == 1001

    report = result.reports[0]
    assert report.status == "ok"
    assert report.fetched == 3
    assert report.kept == 1
    assert report.skipped_by_keyword == 2


def test_non_msis_jobs_are_filtered_out(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    titles = {job.title for job in source.fetch_all_jobs().jobs}

    assert "Warehouse Associate" not in titles
    assert "Senior Director, Field Operations" not in titles


def test_non_us_location_is_filtered_by_default(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs_intl.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.kept_count == 1
    assert result.jobs[0].location == "Chicago, IL"
    assert result.reports[0].skipped_by_filter == 1


def test_unknown_remote_location_is_filtered_by_default(transport):
    payload = {
        "jobs": [
            {
                "id": 9001,
                "title": "Data Analyst",
                "location": {"name": "Remote"},
                "absolute_url": "https://example.com/jobs/9001",
                "content": "Build SQL dashboards and analytics.",
            }
        ]
    }
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=payload,
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.jobs == []
    assert result.reports[0].skipped_by_filter == 1


def test_postings_older_than_a_month_are_filtered_by_default(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs_freshness.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.kept_count == 1
    assert result.jobs[0].source_job_id.endswith(":3001")
    assert result.reports[0].skipped_by_freshness == 1


def test_failed_company_is_reported_not_raised(transport):
    # No route for this board -> transport returns 404 -> provider error.
    source = CompanyCareersSource(
        config=_config([_greenhouse_company(slug="missing")]),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.jobs == []
    assert result.reports[0].status == "failed"
    assert result.reports[0].error


def test_blocked_source_is_reported(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body={"error": "forbidden"},
        status=403,
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.reports[0].status == "blocked"
    assert "Acme" in result.failed_companies()


def test_robots_disallow_skips_company(transport):
    transport.route(
        method="GET",
        contains="/robots.txt",
        body="User-agent: *\nDisallow: /",
        is_json=False,
    )
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()], respect_robots=True),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.reports[0].status == "robots_disallowed"
    assert result.jobs == []


def test_max_total_jobs_per_run_is_enforced(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()], max_total=0 + 1),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert result.kept_count <= 1


def test_max_companies_bounds_the_sweep(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/",
        body=load_fixture("greenhouse_jobs.json"),
    )
    companies = [
        CompanyTarget(
            company_name=f"Acme {index}",
            ats_provider="greenhouse",
            ats_slug=f"acme{index}",
            priority=index,
        )
        for index in range(4)
    ]
    source = CompanyCareersSource(
        config=_config(companies),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs(max_companies=2)

    # Only the two highest-priority companies are contacted at all; the bound
    # has to hold before any request is made, not after filtering.
    assert [report.company_name for report in result.reports] == ["Acme 0", "Acme 1"]
    assert any("Limited to the first 2" in warning for warning in result.warnings)


def test_max_companies_none_sweeps_every_enabled_company(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/",
        body=load_fixture("greenhouse_jobs.json"),
    )
    companies = [
        CompanyTarget(
            company_name=f"Acme {index}",
            ats_provider="greenhouse",
            ats_slug=f"acme{index}",
            priority=index,
        )
        for index in range(3)
    ]
    source = CompanyCareersSource(
        config=_config(companies),
        client=make_client(transport),
    )

    result = source.fetch_all_jobs()

    assert len(result.reports) == 3
    assert not any("Limited to the first" in warning for warning in result.warnings)


def test_to_summary_shape(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    source = CompanyCareersSource(
        config=_config([_greenhouse_company()]),
        client=make_client(transport),
    )

    summary = source.fetch_all_jobs().to_summary()

    assert summary["raw_count"] == 3
    assert summary["kept_count"] == 1
    assert summary["companies_total"] == 1
    assert summary["companies_ok"] == 1
    assert isinstance(summary["per_company"], list)
    assert summary["per_company"][0]["company_name"] == "Acme"

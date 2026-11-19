from hope_job_agent.sources.company_careers.adapter import (
    CompanyFetchReport,
    compute_coverage_summary,
)
from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfig,
    CompanyTarget,
)


def _config() -> CompanyCareersConfig:
    return CompanyCareersConfig(
        companies=[
            CompanyTarget(
                company_name="Verified Co",
                ats_provider="greenhouse",
                ats_slug="verified",
                enabled=True,
                student_interest_rank=1,
                verification_status="verified",
            ),
            CompanyTarget(
                company_name="Unsupported Co",
                ats_provider="static",
                enabled=False,
                student_interest_rank=2,
                verification_status="unsupported",
                unsupported_reason="Custom portal; no public JSON board.",
            ),
            CompanyTarget(
                company_name="Pending Co",
                ats_provider="workday",
                enabled=False,
                student_interest_rank=3,
                verification_status="pending",
            ),
            # Not tracked (no rank): must not affect top-50 metrics.
            CompanyTarget(
                company_name="Extra Co",
                ats_provider="lever",
                ats_slug="extra",
                enabled=True,
            ),
        ]
    )


def test_coverage_summary_counts():
    summary = compute_coverage_summary(_config())

    assert summary["tracked_total"] == 3
    assert summary["verified_enabled"] == 1
    assert summary["verified_unsupported"] == 1
    assert summary["unverified"] == 1
    assert summary["failed_live_smoke"] == []


def test_summary_exposes_lamp_coverage_with_backcompat_alias():
    from hope_job_agent.sources.company_careers.adapter import (
        CompanyCareersFetchResult,
    )

    coverage = compute_coverage_summary(_config())
    result = CompanyCareersFetchResult(
        jobs=[],
        reports=[],
        raw_count=0,
        kept_count=0,
        duplicate_count=0,
        coverage=coverage,
    )
    summary = result.to_summary()
    assert summary["lamp_coverage"] == coverage
    # Consumers written against the original top-50 key must keep working.
    assert summary["top50_coverage"] == coverage


def test_coverage_summary_reports_failed_smoke():
    reports = [
        CompanyFetchReport(
            company_name="Verified Co", provider="greenhouse", status="blocked"
        ),
        CompanyFetchReport(company_name="Extra Co", provider="lever", status="failed"),
    ]
    summary = compute_coverage_summary(_config(), reports)

    # Only tracked companies appear in the top-50 smoke list.
    assert summary["failed_live_smoke"] == ["Verified Co"]

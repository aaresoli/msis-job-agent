from datetime import UTC, datetime

from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfig,
    CompanyTarget,
)
from hope_job_agent.sources.company_careers.reporting import (
    build_health_stats,
    build_quality_audit,
    render_health_markdown,
    render_quality_markdown,
)

NOW = datetime(2026, 7, 8, tzinfo=UTC)


def _config() -> CompanyCareersConfig:
    return CompanyCareersConfig(
        companies=[
            CompanyTarget(
                company_name="Fresh Co",
                ats_provider="greenhouse",
                ats_slug="fresh",
                enabled=True,
                student_interest_rank=1,
                verification_status="verified",
                verified_at="2026-07-01",
            ),
            CompanyTarget(
                company_name="Stale Co",
                ats_provider="workday",
                host="stale.wd1.myworkdayjobs.com",
                tenant="stale",
                site="External",
                enabled=True,
                student_interest_rank=2,
                verification_status="verified",
                verified_at="2026-01-01",
            ),
            CompanyTarget(
                company_name="Merged Canonical",
                ats_provider="static",
                enabled=False,
                student_interest_rank=3,
                merged_excel_ranks=[5],
                verification_status="unsupported",
                unsupported_reason="No public endpoint.",
            ),
            CompanyTarget(
                company_name="Pending Co",
                ats_provider="workday",
                enabled=False,
                student_interest_rank=4,
                verification_status="pending",
            ),
        ]
    )


def _run_summary() -> dict:
    return {
        "company_careers_health": {
            "raw_count": 100,
            "kept_count": 30,
            "duplicate_count": 3,
            "companies_total": 5,
            "companies_ok": 3,
            "warnings": [
                "Reached max_total_jobs_per_run=4000; remaining companies skipped."
            ],
            "per_company": [
                {
                    "company_name": "Fresh Co",
                    "provider": "greenhouse",
                    "status": "ok",
                    "fetched": 50,
                    "kept": 30,
                },
                {
                    "company_name": "Stale Co",
                    "provider": "workday",
                    "status": "ok",
                    "fetched": 30,
                    "kept": 0,
                },
                {
                    "company_name": "Failed Co",
                    "provider": "workday",
                    "status": "failed",
                    "fetched": 0,
                    "kept": 0,
                },
                {
                    "company_name": "Blocked Co",
                    "provider": "workday",
                    "status": "blocked",
                    "fetched": 0,
                    "kept": 0,
                },
                {
                    "company_name": "Robots Co",
                    "provider": "smartrecruiters",
                    "status": "robots_disallowed",
                    "fetched": 0,
                    "kept": 0,
                },
                {
                    "company_name": "Empty Co",
                    "provider": "lever",
                    "status": "empty",
                    "fetched": 0,
                    "kept": 0,
                },
            ],
        }
    }


def test_health_stats_ranks_and_statuses():
    stats = build_health_stats(
        _config(), run_summary=_run_summary(), stale_days=30, now=NOW
    )
    cfg = stats["config"]
    # 4 tracked entries cover 5 Excel ranks via the merged alias.
    assert cfg["tracked_ranked"] == 4
    assert cfg["ranks_covered_total"] == 5
    assert cfg["merged_alias_ranks"] == {5: "Merged Canonical"}
    assert cfg["pending_ranked"] == 1
    assert [s["company"] for s in cfg["stale_verified"]] == ["Stale Co"]

    run = stats["run"]
    assert run["failed"] == ["Failed Co"]
    assert run["blocked"] == ["Blocked Co"]
    assert run["robots_disallowed"] == ["Robots Co"]
    assert run["empty"] == ["Empty Co"]
    assert run["zero_kept"] == ["Stale Co"]
    assert run["cap_hit"] is True
    assert run["duplicate_count"] == 3
    assert run["provider_breakdown"]["workday"]["companies"] == 3
    assert run["provider_breakdown"]["greenhouse"]["kept"] == 30


def test_health_markdown_renders_key_sections():
    stats = build_health_stats(
        _config(), run_summary=_run_summary(), stale_days=30, now=NOW
    )
    markdown = render_health_markdown(stats)
    assert "Excel ranks covered: **5**" in markdown
    assert "Stale Co" in markdown
    assert "cap hit: YES" in markdown
    assert "| workday | 3 |" in markdown
    assert "intentional compliance outcomes" in markdown


def _jobs() -> list[dict]:
    rows = []
    for i in range(6):
        rows.append(
            {
                "source_job_id": f"greenhouse:acme:{i}",
                "company": "Acme",
                "title": f"Senior Director, Platform {i}",
                "concentration_tags": "Data Analytics and AI",
            }
        )
    rows.append(
        {
            "source_job_id": "workday:beta:1",
            "company": "Beta",
            "title": "Business Systems Analyst",
            "concentration_tags": "Digital Enterprise Systems and AI",
        }
    )
    rows.append(
        {
            "source_job_id": "workday:beta:2",
            "company": "Beta",
            "title": "Community Happiness Wrangler",
            "concentration_tags": "",
        }
    )
    return rows


def test_quality_audit_flags():
    run_summary = {
        "company_careers_health": {
            "per_company": [
                {
                    "company_name": "Acme",
                    "provider": "greenhouse",
                    "status": "ok",
                    "fetched": 100,
                    "kept": 2,
                },
                {
                    "company_name": "Beta",
                    "provider": "workday",
                    "status": "ok",
                    "fetched": 40,
                    "kept": 0,
                },
            ]
        }
    }
    audit = build_quality_audit(_jobs(), run_summary, sample_size=3)

    assert audit["total_jobs"] == 8
    assert audit["by_provider"] == {"greenhouse": 6, "workday": 2}
    # All six Acme keeps are senior-titled -> senior-heavy flag.
    assert audit["senior_heavy_companies"][0]["company"] == "Acme"
    assert audit["senior_heavy_companies"][0]["share"] == 1.0
    # "Community Happiness Wrangler" has no MSIS-ish token.
    assert audit["suspicious_generic_titles"] == [
        {"company": "Beta", "title": "Community Happiness Wrangler"}
    ]
    assert audit["zero_kept_companies"] == ["Beta"]
    assert audit["low_keep_ratio_companies"][0]["company"] == "Acme"
    assert "Cybersecurity and Risk Analytics" in audit[
        "missing_concentration_families"
    ]
    assert set(audit["samples_by_provider"]) == {"greenhouse", "workday"}


def test_quality_markdown_renders():
    audit = build_quality_audit(_jobs(), None, sample_size=2)
    markdown = render_quality_markdown(audit)
    assert "# ATS Quality Audit" in markdown
    assert "Senior-heavy companies" in markdown
    assert "Samples by provider" in markdown

import json
from datetime import date

import pytest

from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.data_quality import (
    DEFAULT_THRESHOLDS_PATH,
    DataQualityThresholds,
    DataQualityThresholdsError,
    build_data_quality_report,
    load_data_quality_thresholds,
)

LONG_DESCRIPTION = (
    "This is a detailed data analytics internship description covering SQL, "
    "Python, dashboards, stakeholder reporting, and business intelligence work "
    "for an approved employer export used by the MSIS job agent pipeline demo."
)


def _complete_job(**overrides) -> JobPosting:
    defaults = {
        "source": "ksbit_export",
        "source_job_id": "complete-1",
        "title": "Data Analyst Intern",
        "company": "Example Analytics",
        "location": "Indianapolis, IN",
        "description": LONG_DESCRIPTION,
        "url": "https://example.com/jobs/complete-1",
        "posted_date": date(2026, 6, 15),
        "employment_type": "Internship",
        "seniority": "Entry",
        "role_tags": ["Data Analyst / BI Engineer"],
        "concentration_tags": ["Data Analytics and AI"],
        "opt_cpt_flag": True,
    }
    return JobPosting(**{**defaults, **overrides})


def _sparse_job(**overrides) -> JobPosting:
    defaults = {
        "source": "ksbit_export",
        "source_job_id": "sparse-1",
        "title": "Campus Assistant",
        "company": "Example Campus",
        "location": "Not specified",
        "description": "Short blurb.",
        "url": "https://example.com/jobs/sparse-1",
        "posted_date": None,
        "role_tags": ["Other"],
        "concentration_tags": [],
        "opt_cpt_flag": None,
    }
    return JobPosting(**{**defaults, **overrides})


def _issue_counts(report) -> dict[str, int]:
    return {issue["key"]: issue["count"] for issue in report["issues"]}


def test_data_quality_report_flags_common_issues():
    jobs = [_complete_job(), _sparse_job()]

    report = build_data_quality_report(
        jobs,
        raw_count=5,
        duplicate_count=1,
        now=date(2026, 7, 1),
    )

    assert report["totals"] == {
        "raw_count": 5,
        "job_count": 2,
        "duplicate_count": 1,
    }
    counts = _issue_counts(report)
    assert counts["missing_location"] == 1
    assert counts["missing_posted_date"] == 1
    assert counts["short_description"] == 1
    assert counts["unknown_opt_cpt"] == 1
    assert counts["unclassified_role"] == 1
    assert counts["unclassified_concentration"] == 1
    assert counts["invalid_url"] == 0


def test_data_quality_report_reports_distributions_and_completeness():
    jobs = [_complete_job(), _sparse_job()]

    report = build_data_quality_report(jobs, now=date(2026, 7, 1))

    assert report["distributions"]["opt_cpt"] == {"friendly": 1, "unknown": 1}
    assert report["distributions"]["by_concentration_tag"] == {
        "Data Analytics and AI": 1,
        "Unclassified": 1,
    }
    assert report["field_completeness"]["location"]["present"] == 1
    assert report["field_completeness"]["posted_date"]["missing"] == 1
    assert 0.0 < report["overall_completeness_pct"] <= 100.0


def test_data_quality_report_flags_stale_postings():
    jobs = [_complete_job(posted_date=date(2026, 1, 1))]

    report = build_data_quality_report(
        jobs,
        now=date(2026, 7, 1),
        stale_after_days=90,
    )

    assert _issue_counts(report)["stale_posting"] == 1


def test_data_quality_report_handles_empty_job_list():
    report = build_data_quality_report([], raw_count=0)

    assert report["totals"]["job_count"] == 0
    assert report["overall_completeness_pct"] == 0.0
    assert all(issue["count"] == 0 for issue in report["issues"])


def test_committed_thresholds_config_loads_defaults():
    thresholds = load_data_quality_thresholds(DEFAULT_THRESHOLDS_PATH)

    assert thresholds == DataQualityThresholds()


def test_thresholds_loader_rejects_unknown_keys(tmp_path):
    config_path = tmp_path / "thresholds.json"
    config_path.write_text(
        json.dumps({"short_description_chars": 150, "unexpected": 1}),
        encoding="utf-8",
    )

    with pytest.raises(DataQualityThresholdsError, match="extra=\\['unexpected'\\]"):
        load_data_quality_thresholds(config_path)


def test_thresholds_flow_into_report_and_are_recorded():
    jobs = [_complete_job(description="Short but acceptable normally.")]

    report = build_data_quality_report(
        jobs,
        now=date(2026, 7, 1),
        short_description_chars=500,
        stale_after_days=5,
    )

    assert report["thresholds"] == {
        "short_description_chars": 500,
        "stale_after_days": 5,
    }
    # A 500-char threshold flags the deliberately shorter description.
    assert _issue_counts(report)["short_description"] == 1

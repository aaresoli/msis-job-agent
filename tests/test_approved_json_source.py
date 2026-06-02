import json
from datetime import date

import pytest

from hope_job_agent.sources.approved_json import (
    ApprovedJsonJobSource,
    ApprovedJsonSourceError,
)


def _export_payload(jobs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "metadata": {
            "source_name": "approved_test_export",
            "source_owner": "Graduate Career Services",
            "approved_by": "Faculty Advisor",
            "approval_date": "2026-06-02",
            "access_method": "Local approved test export",
            "terms_reviewed": True,
        },
        "jobs": jobs,
    }


def test_approved_json_source_fetches_jobs_with_metadata_default_source(tmp_path):
    export_path = tmp_path / "jobs.json"
    export_path.write_text(
        json.dumps(
            _export_payload(
                [
                    {
                        "title": "Data Analyst Intern",
                        "company": "Example Analytics",
                        "location": "Bloomington, IN",
                        "description": "Analyze data with SQL and Python.",
                        "url": "https://example.com/jobs/data-analyst",
                        "posted_date": "2026-05-20",
                        "concentration_tags": ["Business Analytics"],
                        "opt_cpt_flag": True,
                    }
                ]
            )
        ),
        encoding="utf-8",
    )

    source = ApprovedJsonJobSource(export_path)
    jobs = source.fetch_jobs()

    assert source.health_check() is True
    assert source.source_name == "approved_test_export"
    assert jobs[0].source == "approved_test_export"
    assert jobs[0].title == "Data Analyst Intern"
    assert jobs[0].posted_date == date(2026, 5, 20)
    assert jobs[0].opt_cpt_flag is True


def test_approved_json_source_reports_missing_file(tmp_path):
    source = ApprovedJsonJobSource(tmp_path / "missing.json")

    assert source.health_check() is False
    with pytest.raises(ApprovedJsonSourceError, match="not found"):
        source.fetch_jobs()


def test_approved_json_source_reports_malformed_json(tmp_path):
    export_path = tmp_path / "bad.json"
    export_path.write_text("{not-json", encoding="utf-8")

    source = ApprovedJsonJobSource(export_path)

    assert source.health_check() is False
    with pytest.raises(ApprovedJsonSourceError, match="not valid JSON"):
        source.fetch_jobs()


def test_approved_json_source_requires_terms_review(tmp_path):
    export_path = tmp_path / "jobs.json"
    payload = _export_payload([])
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    metadata["terms_reviewed"] = False
    export_path.write_text(json.dumps(payload), encoding="utf-8")

    source = ApprovedJsonJobSource(export_path)

    assert source.health_check() is False
    with pytest.raises(ApprovedJsonSourceError, match="terms_reviewed"):
        source.fetch_jobs()

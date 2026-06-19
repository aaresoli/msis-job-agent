import json
from datetime import date

import pytest

from hope_job_agent.pipeline.runner import run_pipeline
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
            "documentation_url": "https://example.com/source-docs",
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
    result = source.fetch_jobs_with_warnings()
    jobs = result.jobs

    assert source.health_check() is True
    assert source.source_name == "approved_json"
    assert result.metadata.source_name == "approved_test_export"
    assert jobs[0].source == "approved_test_export"
    assert jobs[0].title == "Data Analyst Intern"
    assert jobs[0].posted_date == date(2026, 5, 20)
    assert jobs[0].opt_cpt_flag is True
    assert jobs[0].raw_metadata["approval_metadata"] == {
        "source_name": "approved_test_export",
        "source_owner": "Graduate Career Services",
        "approved_by": "Faculty Advisor",
        "approval_date": "2026-06-02",
        "access_method": "Local approved test export",
        "terms_reviewed": True,
        "documentation_url": "https://example.com/source-docs",
    }


def test_approved_json_source_preserves_url_fallback_and_audit_metadata(tmp_path):
    export_path = tmp_path / "jobs.json"
    export_path.write_text(
        json.dumps(
            _export_payload(
                [
                    {
                        "source_job_id": "job-apply-001",
                        "title": "Data Engineer Intern",
                        "company": "Example Analytics",
                        "location": "Bloomington, IN",
                        "description": "Build data pipelines with Python.",
                        "apply_url": "https://example.com/apply/data-engineer",
                        "raw_metadata": {"batch_id": "approved-batch-1"},
                    }
                ]
            )
        ),
        encoding="utf-8",
    )

    result = ApprovedJsonJobSource(export_path).fetch_jobs_with_warnings()
    job = result.jobs[0]

    assert job.url == "https://example.com/apply/data-engineer"
    assert job.raw_metadata["batch_id"] == "approved-batch-1"
    assert job.raw_metadata["source_job_id"] == "job-apply-001"
    assert job.raw_metadata["approval_metadata"]["approved_by"] == "Faculty Advisor"
    assert job.raw_metadata["approval_metadata"]["terms_reviewed"] is True


def test_approved_json_source_can_be_reused_across_pipeline_runs(tmp_path):
    export_path = tmp_path / "jobs.json"
    output_one = tmp_path / "pipeline_one.json"
    output_two = tmp_path / "pipeline_two.json"
    database_url = f"sqlite:///{(tmp_path / 'pipeline.sqlite3').as_posix()}"
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
                    }
                ]
            )
        ),
        encoding="utf-8",
    )
    source = ApprovedJsonJobSource(export_path)

    first_result = run_pipeline(
        [source],
        output_path=output_one,
        database_url=database_url,
    )
    second_result = run_pipeline(
        [source],
        output_path=output_two,
        database_url=database_url,
    )

    assert source.source_name == "approved_json"
    assert first_result.deduplicated_count == 1
    assert second_result.deduplicated_count == 1


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

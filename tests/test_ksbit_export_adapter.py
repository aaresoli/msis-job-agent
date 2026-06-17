import csv
import json

import pytest

from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline
from hope_job_agent.sources.ksbit_export import (
    KSBIT_SOURCE_NAME,
    KsbitExportSource,
    KsbitExportSourceError,
)
from hope_job_agent.sources.registry import (
    SOURCE_REGISTRY,
    SourceStatus,
    ensure_source_allowed,
)


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_record(**overrides):
    record = {
        "source_job_id": "ksbit-001",
        "title": "Business Analyst Intern",
        "company": "Example Analytics",
        "location": "Bloomington, IN",
        "description": "Use SQL and Python to analyze business data.",
        "apply_url": "https://example.com/ksbit/business-analyst-intern",
        "posted_date": "2026-06-01",
        "employment_type": "Internship",
        "seniority_level": "Entry",
    }
    record.update(overrides)
    return record


def _write_profiles(path):
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "student_id": "student-001",
                        "name": "Data Student",
                        "concentration": "Data Analytics and AI",
                        "academic_stage": "Incoming student (Fall)",
                        "target_roles": ["Data Analyst / BI Engineer"],
                        "skills": ["SQL", "Python"],
                        "work_auth_status": "Need CPT / OPT sponsorship",
                        "geo_preference": ["Midwest (Chicago, Indy, Cincy)"],
                        "delivery_preference": "Dashboard / spreadsheet view",
                        "ai_matching_consent": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_ksbit_export_loads_json_list_input(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, [_valid_record()])

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 1
    assert result.loaded_count == 1
    assert result.skipped_count == 0
    assert result.returned_count == 1
    assert result.jobs[0].source == KSBIT_SOURCE_NAME
    assert result.jobs[0].source_job_id == "ksbit-001"
    assert result.jobs[0].raw_metadata["raw_payload"]["title"] == (
        "Business Analyst Intern"
    )
    assert "ingested_at" in result.jobs[0].raw_metadata
    assert result.jobs[0].retrieved_at is not None


def test_ksbit_export_loads_wrapped_json_input(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, {"results": [_valid_record(source_job_id="ksbit-002")]})

    jobs = KsbitExportSource(export_path).fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].source_job_id == "ksbit-002"


def test_ksbit_export_loads_csv_input(tmp_path):
    export_path = tmp_path / "ksbit_jobs.csv"
    with export_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "job_id",
                "job_title",
                "employer_name",
                "work_location",
                "job_description",
                "job_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "job_id": "ksbit-csv-001",
                "job_title": "Analytics Intern",
                "employer_name": "Example Analytics",
                "work_location": "Chicago, IL",
                "job_description": "Build SQL reports and Python dashboards.",
                "job_url": "https://example.com/ksbit/analytics-intern",
            }
        )

    jobs = KsbitExportSource(export_path).fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].title == "Analytics Intern"
    assert jobs[0].company == "Example Analytics"
    assert jobs[0].url == "https://example.com/ksbit/analytics-intern"


def test_ksbit_export_maps_field_aliases_and_optional_values(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(
        export_path,
        [
            {
                "req_id": "req-123",
                "role": "Cybersecurity Risk Analyst",
                "organization": "Example Security",
                "city": "Indianapolis, IN",
                "summary": "Review SIEM alerts and NIST controls.",
                "post_url": "https://example.com/ksbit/security-risk",
                "created_at": "2026-06-02T10:30:00Z",
                "work_type": "Internship",
                "level": "Entry",
                "concentration_tags": "Cybersecurity; Data Analytics and AI",
                "opt_cpt_flag": "yes",
            }
        ],
    )

    job = KsbitExportSource(export_path).fetch_jobs()[0]

    assert job.source_job_id == "req-123"
    assert job.title == "Cybersecurity Risk Analyst"
    assert job.company == "Example Security"
    assert job.location == "Indianapolis, IN"
    assert job.description == "Review SIEM alerts and NIST controls."
    assert job.posted_date.isoformat() == "2026-06-02"
    assert job.employment_type == "Internship"
    assert job.seniority == "Entry"
    assert job.concentration_tags == ["Cybersecurity", "Data Analytics and AI"]
    assert job.opt_cpt_flag is True


def test_ksbit_export_skips_invalid_rows_with_warnings(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, [_valid_record(), _valid_record(apply_url="")])

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 2
    assert result.loaded_count == 1
    assert result.skipped_count == 1
    assert result.returned_count == 1
    assert result.warnings
    assert "missing required field(s): apply_url" in result.warnings[0]


def test_ksbit_export_rejects_empty_files(tmp_path):
    export_path = tmp_path / "empty.json"
    _write_json(export_path, [])

    with pytest.raises(KsbitExportSourceError, match="empty"):
        KsbitExportSource(export_path).fetch_jobs()


def test_ksbit_export_rejects_unsupported_extensions(tmp_path):
    export_path = tmp_path / "ksbit_jobs.txt"
    export_path.write_text("not supported", encoding="utf-8")

    with pytest.raises(KsbitExportSourceError, match="Unsupported"):
        KsbitExportSource(export_path).fetch_jobs()


def test_ksbit_export_generates_stable_fallback_source_job_id(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    record = _valid_record(source_job_id=None)
    del record["source_job_id"]
    _write_json(export_path, [record])

    first_job = KsbitExportSource(export_path).fetch_jobs()[0]
    second_job = KsbitExportSource(export_path).fetch_jobs()[0]

    assert first_job.source_job_id == second_job.source_job_id
    assert first_job.source_job_id is not None
    assert first_job.source_job_id.startswith("ksbit-")
    assert first_job.raw_metadata["source_job_id_was_generated"] is True


def test_ksbit_export_filters_since_date_and_includes_missing_dates(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(
        export_path,
        [
            _valid_record(source_job_id="old", posted_date="2026-05-01"),
            _valid_record(
                source_job_id="new",
                title="New Analytics Intern",
                apply_url="https://example.com/ksbit/new-analytics",
                posted_date="2026-06-03",
            ),
            _valid_record(
                source_job_id="missing-date",
                title="Missing Date Job",
                apply_url="https://example.com/ksbit/missing-date",
                posted_date="not-a-date",
            ),
        ],
    )

    result = KsbitExportSource(
        export_path,
        since_date="2026-06-01",
    ).fetch_jobs_with_warnings()

    assert [job.source_job_id for job in result.jobs] == ["new", "missing-date"]
    assert result.returned_count == 2
    assert any(
        "without parseable posted_date" in warning for warning in result.warnings
    )


def test_ksbit_export_applies_limit_after_filtering(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(
        export_path,
        [
            _valid_record(source_job_id="one", posted_date="2026-06-01"),
            _valid_record(
                source_job_id="two",
                title="Second Analyst",
                apply_url="https://example.com/ksbit/second",
                posted_date="2026-06-02",
            ),
        ],
    )

    result = KsbitExportSource(
        export_path,
        since_date="2026-06-01",
        limit=1,
    ).fetch_jobs_with_warnings()

    assert result.returned_count == 1
    assert result.jobs[0].source_job_id == "one"


def test_ksbit_export_source_registry_loading():
    metadata = ensure_source_allowed(KSBIT_SOURCE_NAME)

    assert SOURCE_REGISTRY[KSBIT_SOURCE_NAME].status is SourceStatus.APPROVED
    assert metadata.name == KSBIT_SOURCE_NAME


def test_ksbit_export_is_compatible_with_mvp_runner(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    database_path = tmp_path / "mvp.sqlite3"
    _write_json(export_path, [_valid_record()])
    _write_profiles(profiles_path)

    result = run_mvp_pipeline(
        source_name=KSBIT_SOURCE_NAME,
        input_path=export_path,
        profiles_path=profiles_path,
        output_path=output_path,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert output_path.exists()
    assert database_path.exists()
    assert result.summary["source"] == KSBIT_SOURCE_NAME
    assert result.summary["raw_count"] == 1
    assert result.summary["unique_count"] == 1
    assert result.summary["total_ranked_matches"] == 1

"""Tests exercising the committed synthetic 12Twenty Excel fixture.

The fixture mirrors the real KelleyLink/12Twenty schema (JSON location cells,
status values, work-authorization strings, sensitive analytics columns) with
fabricated data, so the Excel path has deterministic coverage without PII.
"""

import json
from pathlib import Path

from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline
from hope_job_agent.sources.ksbit_export import KsbitExportSource

FIXTURE_PATH = Path("data/sample_12twenty_export.xlsx")


def test_committed_12twenty_fixture_exists():
    assert (
        FIXTURE_PATH.exists()
    ), "Run scripts/generate_sample_12twenty_xlsx.py to (re)create the fixture."


def test_adapter_parses_12twenty_schema_variance():
    result = KsbitExportSource(FIXTURE_PATH).fetch_jobs_with_warnings()

    assert result.raw_count == 8
    assert result.returned_count == 6
    assert result.skipped_count == 2
    # Closed status and missing URL are the two skipped rows.
    assert any("Application Closed" in warning for warning in result.warnings)
    assert any("apply_url" in warning for warning in result.warnings)

    locations = {job.location for job in result.jobs}
    assert "Bloomington, IN" in locations  # JSON CityName parsing
    assert "Remote" in locations  # Location Type == Remote

    # Sensitive analytics columns must never surface on the normalized job.
    for job in result.jobs:
        assert "application_count" not in job.raw_metadata
        assert "distinct_applicant_count" not in job.raw_metadata


def test_jobs_only_pipeline_against_12twenty_fixture(tmp_path):
    output_path = tmp_path / "mvp_jobs.csv"

    result = run_mvp_pipeline(
        source_name="kelleylink_excel",
        input_path=FIXTURE_PATH,
        profiles_path=None,
        output_path=output_path,
        skip_store=True,
    )

    assert result.summary["unique_count"] == 6

    data_quality = json.loads(
        output_path.with_name("mvp_jobs.data_quality.json").read_text(encoding="utf-8")
    )
    issue_counts = {issue["key"]: issue["count"] for issue in data_quality["issues"]}
    # Row without a Job Posting ID triggers the generated-id data-quality flag.
    assert issue_counts["generated_source_job_id"] == 1

    concentrations = data_quality["distributions"]["by_concentration_tag"]
    assert "Digital Platforms and Security" in concentrations

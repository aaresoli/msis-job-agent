import csv
import json
from datetime import datetime

from openpyxl import Workbook

from hope_job_agent.pipeline.run_mvp import (
    JOBS_OUTPUT_COLUMNS,
    run_mvp_pipeline,
)
from hope_job_agent.sources.ksbit_export import KsbitExportSource
from hope_job_agent.sources.registry import create_source_adapter
from hope_job_agent.storage import SQLiteJobStore

TWELVE_TWENTY_HEADERS = [
    "Job Posting ID",
    "Job Title",
    "Company Name",
    "Status",
    "Posted Date",
    "Job Description",
    "Application URL",
    "Location",
    "Job Type",
    "Work Authorization Requirement",
]


def _xlsx_record(**overrides):
    record = {
        "Job Posting ID": "xlsx-001",
        "Job Title": "Data Analyst Intern",
        "Company Name": "Example Analytics",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 23, 6, 19, 59),
        "Job Description": (
            "<p>Analyze business data with SQL, Python, and Tableau dashboards "
            "for stakeholder reporting across the organization.</p>"
        ),
        "Application URL": "https://example.com/12twenty/data-analyst-intern",
        "Location": '{"CountryName":"United States (USA)","CityName":"Chicago - IL"}',
        "Job Type": "Internship",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
    }
    record.update(overrides)
    return record


def _write_xlsx(path, records):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(TWELVE_TWENTY_HEADERS)
    for record in records:
        worksheet.append([record.get(header) for header in TWELVE_TWENTY_HEADERS])
    workbook.save(path)


def test_kelleylink_excel_alias_builds_ksbit_adapter(tmp_path):
    export_path = tmp_path / "export.xlsx"
    _write_xlsx(export_path, [_xlsx_record()])

    source = create_source_adapter("kelleylink_excel", export_path)

    assert isinstance(source, KsbitExportSource)
    jobs = source.fetch_jobs()
    assert len(jobs) == 1


def test_jobs_only_mode_writes_all_artifacts(tmp_path):
    export_path = tmp_path / "export.xlsx"
    output_path = tmp_path / "out" / "mvp_jobs.csv"
    _write_xlsx(
        export_path,
        [
            _xlsx_record(),
            _xlsx_record(
                **{
                    "Job Posting ID": "xlsx-002",
                    "Job Title": "Cybersecurity Analyst Intern",
                    "Company Name": "Example Security",
                    "Job Description": (
                        "<p>Investigate SIEM alerts, map NIST controls, and "
                        "triage vulnerabilities for the security team.</p>"
                    ),
                    "Application URL": "https://example.com/12twenty/security",
                }
            ),
        ],
    )

    result = run_mvp_pipeline(
        source_name="kelleylink_excel",
        input_path=export_path,
        profiles_path=None,
        output_path=output_path,
        skip_store=True,
    )

    summary = result.summary
    assert summary["mode"] == "jobs-only"
    assert summary["source"] == "kelleylink_excel"
    assert summary["profile_count"] == 0
    assert summary["total_ranked_matches"] == 0
    assert summary["unique_count"] == 2

    data_quality_path = output_path.with_name("mvp_jobs.data_quality.json")
    gcs_trends_path = output_path.with_name("mvp_jobs.gcs_trends.json")
    summary_path = output_path.with_name("mvp_jobs.summary.json")

    assert output_path.exists()
    assert data_quality_path.exists()
    assert gcs_trends_path.exists()
    assert summary_path.exists()

    with output_path.open(newline="", encoding="utf-8") as jobs_file:
        reader = csv.DictReader(jobs_file)
        rows = list(reader)
    assert reader.fieldnames == JOBS_OUTPUT_COLUMNS
    assert len(rows) == 2

    data_quality = json.loads(data_quality_path.read_text(encoding="utf-8"))
    assert data_quality["totals"]["job_count"] == 2
    assert "by_concentration_tag" in data_quality["distributions"]

    gcs_trends = json.loads(gcs_trends_path.read_text(encoding="utf-8"))
    assert gcs_trends["total_jobs"] == 2


def test_jobs_only_mode_json_output_writes_job_records(tmp_path):
    export_path = tmp_path / "export.xlsx"
    output_path = tmp_path / "mvp_jobs.json"
    _write_xlsx(export_path, [_xlsx_record()])

    run_mvp_pipeline(
        source_name="kelleylink_excel",
        input_path=export_path,
        profiles_path=None,
        output_path=output_path,
        skip_store=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload[0]["title"] == "Data Analyst Intern"
    assert payload[0]["concentration_tags"]


def test_jobs_only_mode_persists_jobs_without_matches(tmp_path):
    export_path = tmp_path / "export.xlsx"
    output_path = tmp_path / "mvp_jobs.csv"
    database_path = tmp_path / "jobs_only.sqlite3"
    _write_xlsx(export_path, [_xlsx_record()])

    run_mvp_pipeline(
        source_name="kelleylink_excel",
        input_path=export_path,
        profiles_path=None,
        output_path=output_path,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert database_path.exists()
    store = SQLiteJobStore(f"sqlite:///{database_path.as_posix()}")
    try:
        counts = store.table_counts(
            "pipeline_runs",
            "deduped_jobs",
            "ranking_scores",
        )
    finally:
        store.close()

    assert counts["pipeline_runs"] == 1
    assert counts["deduped_jobs"] == 1
    assert counts["ranking_scores"] == 0

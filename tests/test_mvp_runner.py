import csv
import json
from datetime import datetime

import pytest
from openpyxl import Workbook

from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.run_mvp import (
    MVP_OUTPUT_COLUMNS,
    MvpPipelineError,
    main,
    run_mvp_pipeline,
)
from hope_job_agent.sources.ksbit_export import KSBIT_SOURCE_NAME
from hope_job_agent.sources.registry import create_source_adapter

TWELVE_TWENTY_DRY_RUN_HEADERS = [
    "Job Posting ID",
    "Job Title",
    "Company Name",
    "Status",
    "Posted Date",
    "Job Description",
    "Application URL",
    "Location",
    "Location Type",
    "Job Type",
    "Work Authorization Requirement",
]


def _write_jobs(path, jobs):
    path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )


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
                    },
                    {
                        "student_id": "student-002",
                        "name": "Security Student",
                        "concentration": "Cybersecurity and Risk Analytics",
                        "academic_stage": "Incoming student (Fall)",
                        "target_roles": ["Cybersecurity Analyst"],
                        "skills": ["SIEM", "NIST"],
                        "work_auth_status": "U.S. Citizen / Green Card",
                        "geo_preference": ["East Coast (NYC, Boston, DC)"],
                        "delivery_preference": "Daily or weekly email",
                        "ai_matching_consent": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_12twenty_xlsx(path, records):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(TWELVE_TWENTY_DRY_RUN_HEADERS)
    for record in records:
        worksheet.append(
            [record.get(header) for header in TWELVE_TWENTY_DRY_RUN_HEADERS]
        )
    workbook.save(path)


def _xlsx_job(**overrides):
    job = {
        "Job Posting ID": "xlsx-data-001",
        "Job Title": "Data Analyst Intern",
        "Company Name": "Example Analytics",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 23, 6, 19, 59),
        "Job Description": (
            "<p>Analyze business data with SQL and Python dashboards.</p>"
        ),
        "Application URL": "https://example.com/12twenty/data-analyst-intern",
        "Location": (
            '{"Rank":0,"CountryName":"United States (USA)",'
            '"CityName":"Bloomington - IN"}'
        ),
        "Location Type": "Specify Location(s)",
        "Job Type": "Internship",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
    }
    job.update(overrides)
    return job


def _data_job(**overrides):
    job = {
        "source_job_id": "job-001",
        "title": "Data Analyst Intern",
        "company": "Example Analytics",
        "location": "Bloomington, IN",
        "description": "Analyze business data with SQL and Python dashboards.",
        "url": "https://example.com/jobs/data-analyst",
        "concentration_tags": ["Business Analytics"],
        "opt_cpt_flag": True,
    }
    job.update(overrides)
    return job


def _security_job(**overrides):
    job = {
        "source_job_id": "job-002",
        "title": "Cybersecurity Analyst Intern",
        "company": "Example Security",
        "location": "Indianapolis, IN",
        "description": "Use SIEM and NIST controls to investigate risk.",
        "url": "https://example.com/jobs/security-analyst",
        "concentration_tags": ["Cybersecurity"],
        "opt_cpt_flag": True,
    }
    job.update(overrides)
    return job


def test_mvp_cli_runs_end_to_end_deduplicates_and_limits_per_student(tmp_path, capsys):
    jobs_path = tmp_path / "jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "outputs" / "mvp_results.csv"
    database_path = tmp_path / "mvp.sqlite3"
    duplicate = _data_job(url="https://example.com/jobs/data-analyst?utm_source=email")
    _write_jobs(jobs_path, [_data_job(), duplicate, _security_job()])
    _write_profiles(profiles_path)

    main(
        [
            "--source",
            "approved_json",
            "--input",
            str(jobs_path),
            "--profiles",
            str(profiles_path),
            "--output",
            str(output_path),
            "--limit",
            "1",
            "--database-url",
            f"sqlite:///{database_path.as_posix()}",
        ]
    )

    captured = capsys.readouterr()
    summary_path = output_path.with_name("mvp_results.summary.json")

    assert "MVP pipeline run complete" in captured.out
    assert output_path.exists()
    assert summary_path.exists()
    assert database_path.exists()

    with output_path.open(newline="", encoding="utf-8") as output_file:
        reader = csv.DictReader(output_file)
        rows = list(reader)

    assert reader.fieldnames == MVP_OUTPUT_COLUMNS
    assert len(rows) == 2
    assert {row["student_id"] for row in rows} == {"student-001", "student-002"}

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["raw_count"] == 3
    assert summary["duplicate_count"] == 1
    assert summary["unique_count"] == 2
    assert summary["classified_count"] == 2
    assert summary["profile_count"] == 2
    assert summary["total_ranked_matches"] == 2
    assert summary["errors"] == []


def test_mvp_runner_warns_and_continues_for_bad_individual_job(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.json"
    malformed_job = _data_job()
    del malformed_job["title"]
    _write_jobs(jobs_path, [_data_job(), malformed_job])
    _write_profiles(profiles_path)

    result = run_mvp_pipeline(
        source_name="approved_json",
        input_path=jobs_path,
        profiles_path=profiles_path,
        output_path=output_path,
        limit=1,
        database_url=f"sqlite:///{(tmp_path / 'mvp.sqlite3').as_posix()}",
    )

    assert output_path.exists()
    assert result.summary["raw_count"] == 2
    assert result.summary["normalized_count"] == 1
    assert result.summary["unique_count"] == 1
    assert result.summary["warnings"]
    assert "Skipped malformed job record" in result.summary["warnings"][0]


def test_mvp_runner_empty_input_gives_clear_error(tmp_path):
    jobs_path = tmp_path / "empty_jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    _write_jobs(jobs_path, [])
    _write_profiles(profiles_path)

    with pytest.raises(MvpPipelineError, match="contains no job records"):
        run_mvp_pipeline(
            source_name="approved_json",
            input_path=jobs_path,
            profiles_path=profiles_path,
            output_path=output_path,
        )


def test_mvp_runner_malformed_input_gives_clear_error(tmp_path):
    jobs_path = tmp_path / "bad_jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    jobs_path.write_text("{not-json", encoding="utf-8")
    _write_profiles(profiles_path)

    with pytest.raises(MvpPipelineError, match="not valid JSON"):
        run_mvp_pipeline(
            source_name="approved_json",
            input_path=jobs_path,
            profiles_path=profiles_path,
            output_path=output_path,
        )


def test_mvp_dry_run_skips_output_and_database_writes(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    database_path = tmp_path / "mvp.sqlite3"
    _write_jobs(jobs_path, [_data_job()])
    _write_profiles(profiles_path)

    result = run_mvp_pipeline(
        source_name="approved_json",
        input_path=jobs_path,
        profiles_path=profiles_path,
        output_path=output_path,
        dry_run=True,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert not output_path.exists()
    assert not result.summary_path.exists()
    assert not database_path.exists()
    assert "Dry run requested" in result.summary["warnings"][-1]


def test_mvp_dry_run_processes_ksbit_xlsx_end_to_end(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "ksbit_xlsx_results.csv"
    database_path = tmp_path / "ksbit_xlsx.sqlite3"
    _write_12twenty_xlsx(
        export_path,
        [
            _xlsx_job(),
            _xlsx_job(
                **{
                    "Job Posting ID": "xlsx-security-001",
                    "Job Title": "Cybersecurity Analyst Intern",
                    "Company Name": "Example Security",
                    "Job Description": (
                        "<p>Use SIEM and NIST controls to investigate risk.</p>"
                    ),
                    "Application URL": (
                        "https://example.com/12twenty/security-analyst-intern"
                    ),
                    "Location": (
                        '{"Rank":0,"CountryName":"United States (USA)",'
                        '"CityName":"Indianapolis - IN"}'
                    ),
                }
            ),
        ],
    )
    _write_profiles(profiles_path)

    source = create_source_adapter(KSBIT_SOURCE_NAME, export_path)
    jobs = source.fetch_jobs()

    assert len(jobs) == 2
    assert all(isinstance(job, JobPosting) for job in jobs)
    assert {job.source for job in jobs} == {KSBIT_SOURCE_NAME}
    assert [job.source_job_id for job in jobs] == [
        "xlsx-data-001",
        "xlsx-security-001",
    ]

    result = run_mvp_pipeline(
        source_name=KSBIT_SOURCE_NAME,
        input_path=export_path,
        profiles_path=profiles_path,
        output_path=output_path,
        dry_run=True,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert not output_path.exists()
    assert not result.summary_path.exists()
    assert not database_path.exists()
    assert result.summary["source"] == KSBIT_SOURCE_NAME
    assert result.summary["raw_count"] == 2
    assert result.summary["normalized_count"] == 2
    assert result.summary["invalid_count"] == 0
    assert result.summary["duplicate_count"] == 0
    assert result.summary["unique_count"] == 2
    assert result.summary["classified_count"] == 2
    assert result.summary["profile_count"] == 2
    assert result.summary["active_profile_count"] == 2
    assert result.summary["total_ranked_matches"] == 4
    assert result.summary["errors"] == []
    assert "Dry run requested" in result.summary["warnings"][-1]
    assert len(result.rows) == 4
    assert {row["source"] for row in result.rows} == {KSBIT_SOURCE_NAME}
    assert {row["title"] for row in result.rows} == {
        "Data Analyst Intern",
        "Cybersecurity Analyst Intern",
    }
    assert all(row["apply_url/post_url"].startswith("https://") for row in result.rows)


def test_mvp_runner_preflights_database_before_writing_outputs(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    _write_jobs(jobs_path, [_data_job()])
    _write_profiles(profiles_path)

    with pytest.raises(MvpPipelineError, match="PostgreSQL persistence failed"):
        run_mvp_pipeline(
            source_name="approved_json",
            input_path=jobs_path,
            profiles_path=profiles_path,
            output_path=output_path,
            database_url="postgresql://user:password@example/jobs",
            storage="postgres",
        )

    assert not output_path.exists()
    assert not output_path.with_name("mvp_results.summary.json").exists()

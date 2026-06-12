import csv
import json

import pytest

from hope_job_agent.pipeline.run_mvp import (
    MVP_OUTPUT_COLUMNS,
    MvpPipelineError,
    main,
    run_mvp_pipeline,
)


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
                        "concentration": "Cybersecurity",
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
        ]
    )

    captured = capsys.readouterr()
    summary_path = output_path.with_name("mvp_results.summary.json")

    assert "MVP pipeline run complete" in captured.out
    assert output_path.exists()
    assert summary_path.exists()

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

import json

import pytest

from hope_job_agent.cli import main


def _write_export(path):
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "source_name": "approved_cli_export",
                    "approved_by": "Faculty Advisor",
                    "approval_date": "2026-06-02",
                    "access_method": "Local approved CLI test export",
                    "terms_reviewed": True,
                },
                "jobs": [
                    {
                        "title": "Data Analyst Intern",
                        "company": "Example Analytics",
                        "location": "Bloomington, IN",
                        "description": "Analyze data with SQL and Python.",
                        "url": "https://example.com/jobs/data-analyst",
                        "concentration_tags": ["Business Analytics"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_cli_run_pipeline_prints_summary_and_writes_output(tmp_path, capsys):
    export_path = tmp_path / "jobs.json"
    output_path = tmp_path / "pipeline_results.json"
    _write_export(export_path)

    main(
        [
            "run-pipeline",
            "--source-file",
            str(export_path),
            "--output-file",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert "Pipeline run complete" in captured.out
    assert "Raw jobs: 1" in captured.out
    assert "Valid jobs: 1" in captured.out
    assert "Invalid jobs: 0" in captured.out
    assert "Deduplicated jobs: 1" in captured.out
    assert str(output_path) in captured.out
    assert output_path.exists()


def test_cli_run_pipeline_fails_for_unreadable_source(tmp_path, capsys):
    missing_path = tmp_path / "missing.json"

    with pytest.raises(SystemExit) as exc_info:
        main(["run-pipeline", "--source-file", str(missing_path)])

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Pipeline failed:" in captured.err
    assert "not found" in captured.err


def test_cli_evaluate_prints_report(capsys):
    main(["evaluate", "--dataset-file", "tests/fixtures/labelled_postings.json"])

    captured = capsys.readouterr()
    assert "Evaluation complete" in captured.out
    assert "Role accuracy:" in captured.out
    assert "Ranking relevance@3:" in captured.out

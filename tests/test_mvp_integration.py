import csv
import json
from collections import defaultdict
from pathlib import Path

from hope_job_agent.pipeline.run_mvp import MVP_OUTPUT_COLUMNS, run_mvp_pipeline
from hope_job_agent.storage import SQLiteJobStore

SAMPLE_JOBS_PATH = Path("data/sample_jobs.json")
SAMPLE_PROFILES_PATH = Path("data/sample_profiles.json")


def test_mvp_pipeline_runs_sample_data_to_ranked_output(tmp_path):
    output_path = tmp_path / "mvp_results.csv"
    summary_path = tmp_path / "mvp_results.summary.json"
    database_path = tmp_path / "mvp.sqlite3"

    result = run_mvp_pipeline(
        source_name="approved_json",
        input_path=SAMPLE_JOBS_PATH,
        profiles_path=SAMPLE_PROFILES_PATH,
        output_path=output_path,
        limit=2,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert output_path.exists()
    assert summary_path.exists()
    assert database_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"] == result.summary["run_id"]
    assert summary["raw_count"] == 6
    assert summary["normalized_count"] == 6
    assert summary["invalid_count"] == 0
    assert summary["duplicate_count"] == 1
    assert summary["unique_count"] == 5
    assert summary["classified_count"] == 5
    assert summary["profile_count"] == 4
    assert summary["active_profile_count"] == 4
    assert summary["total_ranked_matches"] == 8
    assert summary["errors"] == []

    with output_path.open(newline="", encoding="utf-8") as output_file:
        reader = csv.DictReader(output_file)
        rows = list(reader)

    assert reader.fieldnames == MVP_OUTPUT_COLUMNS
    assert len(rows) == 8
    assert len(result.rows) == 8
    assert [row["student_id"] for row in rows] == sorted(
        row["student_id"] for row in rows
    )
    assert {row["source"] for row in rows} == {"approved_local_sample"}

    rows_by_student = _rows_by_student(rows)
    assert set(rows_by_student) == {"msis-001", "msis-002", "msis-003", "msis-004"}
    assert all(len(student_rows) == 2 for student_rows in rows_by_student.values())

    for student_rows in rows_by_student.values():
        scores = [float(row["final_score"]) for row in student_rows]
        assert scores == sorted(scores, reverse=True)
        for row in student_rows:
            score_breakdown = json.loads(row["score_breakdown"])
            assert isinstance(score_breakdown["reasons"], list)
            assert isinstance(score_breakdown["metadata"], dict)
            assert row["ranking_explanation"]
            assert row["apply_url/post_url"].startswith("https://")

    assert _titles_for(rows_by_student["msis-001"]) >= {"Data Analyst Intern"}
    assert _titles_for(rows_by_student["msis-002"]) >= {"Cybersecurity Risk Intern"}

    store = SQLiteJobStore(f"sqlite:///{database_path.as_posix()}")
    try:
        counts = store.table_counts(
            "pipeline_runs",
            "normalized_jobs",
            "deduped_jobs",
            "classification_results",
            "ranking_scores",
            "match_history",
        )
    finally:
        store.close()

    assert counts == {
        "pipeline_runs": 1,
        "normalized_jobs": 5,
        "deduped_jobs": 5,
        "classification_results": 5,
        "ranking_scores": 8,
        "match_history": 8,
    }


def _rows_by_student(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["student_id"]].append(row)
    return dict(grouped)


def _titles_for(rows: list[dict[str, str]]) -> set[str]:
    return {row["title"] for row in rows}

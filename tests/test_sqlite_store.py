import pytest

from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.pipeline.validate import validate_job
from hope_job_agent.scoring.ranker import rank_jobs_for_student
from hope_job_agent.storage import (
    DEFAULT_DATABASE_PATH,
    SQLiteJobStore,
    SQLiteJobStoreError,
    resolve_sqlite_database,
)


def _db_url(path):
    return f"sqlite:///{path.as_posix()}"


def _job(**overrides) -> JobPosting:
    payload = {
        "source": "approved_test_export",
        "source_job_id": "job-001",
        "title": "Data Analyst Intern",
        "company": "Example Analytics",
        "location": "Bloomington, IN",
        "description": "Analyze business data with SQL and Python dashboards.",
        "url": "https://example.com/jobs/data-analyst",
        "concentration_tags": ["Data Analytics and AI"],
        "role_tags": ["Data Analyst / BI Engineer"],
        "opt_cpt_flag": True,
    }
    payload.update(overrides)
    return JobPosting(**payload)


def _profile() -> StudentProfile:
    return StudentProfile(
        student_id="student-001",
        name="Data Student",
        concentration="Data Analytics and AI",
        academic_stage="Incoming student (Fall)",
        target_roles=["Data Analyst / BI Engineer"],
        skills=["SQL", "Python"],
        work_auth_status="Need CPT / OPT sponsorship",
    )


def _persist_jobs(store: SQLiteJobStore, run_id: str, jobs: list[JobPosting]) -> None:
    normalized_jobs = [normalize_job(job) for job in jobs]
    valid_jobs = [job for job in normalized_jobs if validate_job(job)]
    unique_jobs = deduplicate_jobs(valid_jobs)
    classified_jobs = [classify_job_posting(job) for job in unique_jobs]
    profile = _profile()
    matches = rank_jobs_for_student(profile, classified_jobs)
    summary = {
        "run_id": run_id,
        "timestamp": "2026-06-15T00:00:00+00:00",
        "source": "approved_test_export",
        "raw_count": len(jobs),
        "normalized_count": len(normalized_jobs),
        "valid_count": len(valid_jobs),
        "invalid_count": len(normalized_jobs) - len(valid_jobs),
        "duplicate_count": len(valid_jobs) - len(unique_jobs),
        "unique_count": len(unique_jobs),
        "classified_count": len(classified_jobs),
        "profile_count": 1,
        "active_profile_count": 1,
        "total_ranked_matches": len(matches),
        "warnings": [],
        "errors": [],
        "runtime_seconds": 0.01,
    }
    store.persist_pipeline_run(
        run_id=run_id,
        run_type="test",
        source="approved_test_export",
        summary=summary,
        normalized_jobs=normalized_jobs,
        valid_jobs=valid_jobs,
        deduped_jobs=classified_jobs,
        ranked_matches=[(profile, matches)],
    )


def test_resolve_sqlite_database_urls(tmp_path):
    default_database = resolve_sqlite_database("")
    assert default_database.path == DEFAULT_DATABASE_PATH
    assert default_database.database == str(DEFAULT_DATABASE_PATH)

    memory_database = resolve_sqlite_database("sqlite:///:memory:")
    assert memory_database.database == ":memory:"
    assert memory_database.path is None

    db_path = tmp_path / "jobs.sqlite3"
    file_database = resolve_sqlite_database(_db_url(db_path))
    assert file_database.path == db_path
    assert file_database.database == str(db_path)

    with pytest.raises(SQLiteJobStoreError, match="Only empty DATABASE_URL"):
        resolve_sqlite_database("postgresql://user:password@example/jobs")


def test_repeated_pipeline_persistence_upserts_without_duplicates(tmp_path):
    store = SQLiteJobStore(_db_url(tmp_path / "jobs.sqlite3"))

    try:
        _persist_jobs(store, "run-1", [_job()])
        _persist_jobs(store, "run-2", [_job()])

        assert store.table_counts(
            "pipeline_runs",
            "normalized_jobs",
            "deduped_jobs",
            "classification_results",
            "ranking_scores",
            "match_history",
        ) == {
            "pipeline_runs": 2,
            "normalized_jobs": 1,
            "deduped_jobs": 1,
            "classification_results": 1,
            "ranking_scores": 1,
            "match_history": 1,
        }
    finally:
        store.close()


@pytest.mark.parametrize(
    ("first_job", "second_job"),
    [
        (
            _job(source_job_id="same-source", url="https://example.com/jobs/first"),
            _job(source_job_id="same-source", url="https://example.com/jobs/second"),
        ),
        (
            _job(source_job_id="first-id", url="https://example.com/jobs/shared"),
            _job(
                source_job_id="second-id",
                url="https://example.com/jobs/shared?utm_source=email",
            ),
        ),
        (
            _job(source_job_id=None, url="https://example.com/jobs/content-1"),
            _job(source_job_id=None, url="https://example.com/jobs/content-2"),
        ),
    ],
)
def test_alternate_duplicate_signals_resolve_to_one_job(
    tmp_path,
    first_job,
    second_job,
):
    store = SQLiteJobStore(_db_url(tmp_path / "jobs.sqlite3"))

    try:
        _persist_jobs(store, "run-1", [first_job])
        _persist_jobs(store, "run-2", [second_job])

        counts = store.table_counts("pipeline_runs", "deduped_jobs")
        assert counts["pipeline_runs"] == 2
        assert counts["deduped_jobs"] == 1
    finally:
        store.close()

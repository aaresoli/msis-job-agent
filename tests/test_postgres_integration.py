"""PostgreSQL integration tests (require Docker postgres + migrations)."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from hope_job_agent.config.database import build_postgres_url, embedding_dimension
from hope_job_agent.db.session import (
    create_db_engine,
    create_session_factory,
    session_scope,
)
from hope_job_agent.models.job import JobPosting
from hope_job_agent.persistence.embedding_repository import EmbeddingRepository
from hope_job_agent.persistence.job_repository import JobPostingRepository

pytestmark = pytest.mark.postgres


def _postgres_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    return build_postgres_url()


def _can_connect() -> bool:
    try:
        engine = create_db_engine(_postgres_url(), storage="postgres")
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        engine.dispose()
        return True
    except Exception:
        return False


if not _can_connect():
    pytest.skip(
        "PostgreSQL is not available; start docker compose postgres and run "
        "alembic upgrade head",
        allow_module_level=True,
    )


# Every posting these tests create carries this in its external id, so the
# teardown below can find them again. The runbook tells operators to run
# `pytest -m postgres` against the live stack, and without a sweep these rows
# accumulate in the operational database on every run -- they had already
# outnumbered the real corpus.
TEST_JOB_PREFIX = "pytest-pg-"


@pytest.fixture(scope="module")
def session_factory():
    engine = create_db_engine(_postgres_url(), storage="postgres")
    factory = create_session_factory(engine)
    yield factory
    _delete_test_rows(factory)
    engine.dispose()


def _delete_test_rows(factory) -> None:
    """Remove every posting this module created, and anything hanging off it.

    Embeddings and matches reference job_postings, so they go first. Failures
    are swallowed: a cleanup that raises would turn a green run red and hide
    the actual test results.
    """

    pattern = f"{TEST_JOB_PREFIX}%"
    try:
        with session_scope(factory) as session:
            session.execute(
                text(
                    "DELETE FROM job_embeddings WHERE job_id IN "
                    "(SELECT id FROM job_postings WHERE external_job_id LIKE :p)"
                ),
                {"p": pattern},
            )
            session.execute(
                text(
                    "DELETE FROM job_matches WHERE job_id IN "
                    "(SELECT id FROM job_postings WHERE external_job_id LIKE :p)"
                ),
                {"p": pattern},
            )
            session.execute(
                text("DELETE FROM job_postings WHERE external_job_id LIKE :p"),
                {"p": pattern},
            )
    except Exception:  # noqa: BLE001 - cleanup must not mask test outcomes
        pass


def _job(job_id: str) -> JobPosting:
    # The title carries job_id so each test gets a genuinely distinct posting.
    # Repositories dedupe on a canonical fingerprint of title, company, and
    # location, so a shared title made every test collapse onto the first
    # test's row -- and inherit its embedding.
    external_id = f"{TEST_JOB_PREFIX}{job_id}"
    return JobPosting(
        source="ksbit_export",
        source_job_id=external_id,
        title=f"Data Analyst Intern {external_id}",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Analyze business data with SQL and dashboards.",
        url=f"https://example.com/jobs/{external_id}",
        concentration_tags=["Data Analytics and AI"],
    )


@pytest.mark.postgres
def test_job_repository_upsert_and_duplicate_detection(session_factory):
    job = _job(f"pg-{uuid.uuid4().hex[:8]}")
    with session_scope(session_factory) as session:
        repo = JobPostingRepository(session)
        first = repo.upsert_job(job)
        duplicate = repo.find_duplicate(
            job.model_copy(update={"title": "Updated title"})
        )
        assert duplicate is not None
        assert duplicate.id == first.id
        # The dashboard reads the full payload, not the flattened columns.
        assert first.job_json is not None
        assert first.job_json["title"] == job.title
        assert first.job_json["concentration_tags"] == job.concentration_tags
        assert "career_track" in first.job_json


@pytest.mark.postgres
def test_embedding_repository_stores_vector(session_factory):
    job = _job(f"embed-{uuid.uuid4().hex[:8]}")
    # Resolve the width the same way the models do. Reading the environment
    # directly here meant the test carried its own default (1536) while the
    # application defaulted to 768, so the vector never matched the column.
    vector = [0.01] * embedding_dimension()
    # A model name unique to this run. Ranking "nearest overall" only isolates
    # the test on an empty database; against the live one the runbook tells
    # operators to test against (`pytest -m postgres` with the stack up), every
    # previously stored vector competes for the top slot and the assertion
    # fails on a working system.
    model = f"test-model-{uuid.uuid4().hex[:8]}"
    with session_scope(session_factory) as session:
        jobs = JobPostingRepository(session)
        embeddings = EmbeddingRepository(session)
        record = jobs.upsert_job(job)
        embedding = embeddings.upsert_embedding(
            record.id,
            vector,
            model=model,
            input_hash="hash-1",
        )
        assert embedding.job_id == record.id
        results = embeddings.similarity_search(vector, limit=1, embedding_model=model)
        assert results
        assert results[0][0].id == record.id


@pytest.mark.postgres
def test_jobs_without_embeddings_still_persist(session_factory):
    job = _job(f"no-embed-{uuid.uuid4().hex[:8]}")
    with session_scope(session_factory) as session:
        repo = JobPostingRepository(session)
        record = repo.upsert_job(job)
        assert record.embedding is None


@pytest.mark.postgres
def test_similarity_search_ignores_vectors_from_another_embedding_model(
    session_factory,
):
    """Distances between two embedding models are arithmetic without meaning.

    The width check at the call site cannot catch this: nomic-embed-text and
    embeddinggemma are both 768-dimensional, so swapping one for the other
    would silently return nonsense rankings rather than fail. Filtering on the
    model turns that into missing results, which is diagnosable.
    """

    job = _job(f"model-filter-{uuid.uuid4().hex[:8]}")
    vector = [0.02] * embedding_dimension()
    with session_scope(session_factory) as session:
        record = JobPostingRepository(session).upsert_job(job)
        embeddings = EmbeddingRepository(session)
        embeddings.upsert_embedding(
            record.id, vector, model="embeddinggemma", input_hash="hash-model-1"
        )

        matching = embeddings.similarity_search(
            vector, limit=50, embedding_model="embeddinggemma"
        )
        assert record.id in {job.id for job, _ in matching}

        other = embeddings.similarity_search(
            vector, limit=50, embedding_model="nomic-embed-text"
        )
        assert record.id not in {job.id for job, _ in other}


@pytest.mark.postgres
def test_get_embedding_reports_the_stored_input_hash(session_factory):
    """Lets a batch caller skip unchanged postings without re-embedding them."""

    job = _job(f"embed-hash-{uuid.uuid4().hex[:8]}")
    vector = [0.03] * embedding_dimension()
    with session_scope(session_factory) as session:
        record = JobPostingRepository(session).upsert_job(job)
        embeddings = EmbeddingRepository(session)
        assert embeddings.get_embedding(record.id) is None

        embeddings.upsert_embedding(
            record.id, vector, model="embeddinggemma", input_hash="hash-abc"
        )
        stored = embeddings.get_embedding(record.id)
        assert stored is not None
        assert stored.embedding_input_hash == "hash-abc"
        assert stored.embedding_model == "embeddinggemma"

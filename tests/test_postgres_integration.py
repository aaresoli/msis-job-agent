"""PostgreSQL integration tests (require Docker postgres + migrations)."""

from __future__ import annotations

import os
import uuid

import pytest

from hope_job_agent.config.database import build_postgres_url
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


@pytest.fixture(scope="module")
def session_factory():
    engine = create_db_engine(_postgres_url(), storage="postgres")
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


def _job(job_id: str) -> JobPosting:
    return JobPosting(
        source="ksbit_export",
        source_job_id=job_id,
        title="Data Analyst Intern",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Analyze business data with SQL and dashboards.",
        url=f"https://example.com/jobs/{job_id}",
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


@pytest.mark.postgres
def test_embedding_repository_stores_vector(session_factory):
    job = _job(f"embed-{uuid.uuid4().hex[:8]}")
    vector = [0.01] * int(os.getenv("EMBEDDING_DIMENSION", "1536"))
    with session_scope(session_factory) as session:
        jobs = JobPostingRepository(session)
        embeddings = EmbeddingRepository(session)
        record = jobs.upsert_job(job)
        embedding = embeddings.upsert_embedding(
            record.id,
            vector,
            model="test-model",
            input_hash="hash-1",
        )
        assert embedding.job_id == record.id
        results = embeddings.similarity_search(vector, limit=1)
        assert results
        assert results[0][0].id == record.id


@pytest.mark.postgres
def test_jobs_without_embeddings_still_persist(session_factory):
    job = _job(f"no-embed-{uuid.uuid4().hex[:8]}")
    with session_scope(session_factory) as session:
        repo = JobPostingRepository(session)
        record = repo.upsert_job(job)
        assert record.embedding is None

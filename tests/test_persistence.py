"""Unit tests for SQLAlchemy models and persistence helpers."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hope_job_agent.classification.taxonomy import (
    LEGACY_CONCENTRATION_ALIASES,
    MSIS_CONCENTRATIONS,
    normalize_concentration,
    normalize_concentrations,
)
from hope_job_agent.db import models as db_models
from hope_job_agent.models.job import JobPosting
from hope_job_agent.persistence.dedup import (
    canonicalize_job_url,
    compute_canonical_fingerprint,
    compute_content_hash,
    source_external_identity,
)
from hope_job_agent.persistence.job_repository import JobPostingRepository
from hope_job_agent.persistence.source_run_repository import SourceRunRepository
from hope_job_agent.storage.memory_store import MemoryJobStore


@pytest.mark.unit
def test_sqlalchemy_models_import_successfully():
    assert db_models.JobPostingRecord.__tablename__ == "job_postings"
    assert db_models.JobEmbedding.__tablename__ == "job_embeddings"
    assert db_models.SourceRun.__tablename__ == "source_runs"


@pytest.mark.unit
def test_legacy_concentration_aliases_map_to_official_names():
    for alias, official in LEGACY_CONCENTRATION_ALIASES.items():
        assert normalize_concentration(alias) == official
        assert official in MSIS_CONCENTRATIONS


@pytest.mark.unit
def test_normalize_concentrations_outputs_official_names_only():
    tags = normalize_concentrations(["CRA", "Business Analytics", "DPS", "invalid"])
    assert tags == [
        "Data Analytics and AI",
        "Cybersecurity and Risk Analytics",
        "Digital Platforms and Security",
    ]


def _sample_job(**overrides) -> JobPosting:
    payload = {
        "source": "ksbit_export",
        "source_job_id": "job-100",
        "title": "Data Analyst Intern",
        "company": "Example Analytics",
        "location": "Bloomington, IN",
        "description": "Analyze business data with SQL and Python dashboards.",
        "url": "https://example.com/jobs/data-analyst?utm_source=email",
        "concentration_tags": ["CRA"],
    }
    payload.update(overrides)
    return JobPosting(**payload)


@pytest.mark.unit
def test_dedup_helpers_compute_stable_identities():
    job = _sample_job()
    assert source_external_identity(job) == ("ksbit_export", "job-100")
    assert canonicalize_job_url(job) == "https://example.com/jobs/data-analyst"
    assert compute_content_hash(job) == compute_content_hash(job)
    assert compute_canonical_fingerprint(job) == compute_canonical_fingerprint(job)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self._by_type: dict[type, dict[object, object]] = {}

    def add(self, obj: object) -> None:
        self.added.append(obj)
        store = self._by_type.setdefault(type(obj), {})
        if hasattr(obj, "id"):
            store[obj.id] = obj

    def flush(self) -> None:
        return None

    def get(self, model, object_id):
        return self._by_type.get(model, {}).get(object_id)

    def scalar(self, _stmt):
        return None

    def scalars(self, _stmt):
        return []


@pytest.mark.unit
def test_job_repository_upsert_inserts_new_job():
    session = _FakeSession()
    repo = JobPostingRepository(session)  # type: ignore[arg-type]
    repo.find_duplicate = lambda _job: None  # type: ignore[method-assign, assignment]
    repo._companies.get_or_create_company = lambda name, metadata=None: type(  # type: ignore[method-assign, assignment]
        "Company", (), {"id": uuid.uuid4()}
    )()

    record = repo.upsert_job(_sample_job())
    assert record.source == "ksbit_export"
    assert record.concentration_tags == ["Cybersecurity and Risk Analytics"]


@pytest.mark.unit
def test_source_run_repository_records_successful_run():
    session = _FakeSession()
    repo = SourceRunRepository(session)  # type: ignore[arg-type]
    run = repo.start_run("kelleylink_excel")
    finished = repo.finish_run(
        run.id,
        summary={"raw_count": 3, "jobs_inserted": 2, "jobs_updated": 1, "errors": []},
    )
    assert finished.run_status == "success"
    assert finished.jobs_inserted == 2


@pytest.mark.unit
def test_source_run_repository_records_failed_run():
    session = _FakeSession()
    repo = SourceRunRepository(session)  # type: ignore[arg-type]
    run = repo.start_run("company_careers")
    failed = repo.fail_run(run.id, "network error")
    assert failed.run_status == "failed"
    assert failed.error_summary == "network error"


@pytest.mark.unit
def test_memory_store_dry_run_persists_in_memory_only():
    store = MemoryJobStore()
    job = _sample_job()
    store.persist_pipeline_run(
        run_id=str(uuid.uuid4()),
        run_type="test",
        source="ksbit_export",
        summary={"raw_count": 1},
        normalized_jobs=[job],
        valid_jobs=[job],
        deduped_jobs=[job],
        ranked_matches=[],
    )
    assert store.table_counts("job_postings")["job_postings"] == 1
    assert store.table_counts("source_runs")["source_runs"] == 1


@pytest.mark.unit
def test_run_mvp_dry_run_does_not_persist(tmp_path):
    import json

    from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline

    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "source_name": "approved_test_export",
                    "approved_by": "Tester",
                    "approval_date": "2026-06-01",
                    "access_method": "local fixture",
                    "terms_reviewed": True,
                },
                "jobs": [
                    {
                        "source": "approved_test_export",
                        "title": "Analyst",
                        "company": "Co",
                        "location": "Indy",
                        "description": "SQL",
                        "url": "https://example.com/1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    created: list[MemoryJobStore] = []

    def factory(_url):
        store = MemoryJobStore()
        created.append(store)
        return store

    run_mvp_pipeline(
        source_name="approved_json",
        input_path=jobs_path,
        profiles_path=None,
        output_path=tmp_path / "out.csv",
        dry_run=True,
        store_factory=factory,
    )
    assert created == []


@pytest.mark.unit
def test_kelleylink_adapter_can_write_to_memory_store(tmp_path):
    from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline

    store = MemoryJobStore()

    def factory(_url):
        return store

    run_mvp_pipeline(
        source_name="kelleylink_excel",
        input_path=Path("data/sample_12twenty_export.xlsx"),
        profiles_path=None,
        output_path=tmp_path / "jobs.csv",
        storage="memory",
        store_factory=factory,
    )
    assert len(store.jobs) >= 1


@pytest.mark.unit
def test_import_existing_jobs_dry_run(tmp_path):
    import json

    from hope_job_agent.db.import_existing_jobs import import_jobs_from_file

    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "source_name": "approved_test_export",
                    "approved_by": "Tester",
                    "approval_date": "2026-06-01",
                    "access_method": "local fixture",
                    "terms_reviewed": True,
                },
                "jobs": [
                    {
                        "source": "approved_test_export",
                        "title": "Analyst",
                        "company": "Co",
                        "location": "Indy",
                        "description": "SQL",
                        "url": "https://example.com/1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary = import_jobs_from_file(
        jobs_path,
        source_name="approved_json",
        dry_run=True,
    )
    assert summary["unique"] == 1
    assert summary["inserted"] == 0

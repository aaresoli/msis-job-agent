"""Tests for storage factory and memory backend."""

import pytest

from hope_job_agent.config.database import get_database_settings
from hope_job_agent.storage import (
    JobStore,
    JobStoreError,
    MemoryJobStore,
    PostgresJobStore,
    SQLiteJobStore,
    create_job_store,
)


@pytest.fixture
def no_ambient_database_url(monkeypatch):
    """Assert the default with no DATABASE_URL in the environment.

    ``storage="auto"`` deliberately honours DATABASE_URL when it is set, so
    this test has to clear it. Otherwise it passes or fails depending on
    whether the developer or CI job happens to have a database configured.
    """

    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_database_settings.cache_clear()
    yield
    get_database_settings.cache_clear()


@pytest.mark.unit
def test_create_job_store_returns_sqlite_for_empty_url(no_ambient_database_url):
    store = create_job_store("")
    try:
        assert isinstance(store, SQLiteJobStore)
        assert isinstance(store, JobStore)
    finally:
        store.close()


@pytest.mark.unit
def test_create_job_store_returns_sqlite_for_memory_storage_mode():
    store = create_job_store("", storage="sqlite")
    try:
        assert isinstance(store, SQLiteJobStore)
    finally:
        store.close()


@pytest.mark.unit
def test_create_job_store_returns_memory_store():
    store = create_job_store("", storage="memory")
    try:
        assert isinstance(store, MemoryJobStore)
    finally:
        store.close()


@pytest.mark.unit
def test_create_job_store_returns_postgres_for_postgres_url():
    store = create_job_store(
        "postgresql+psycopg://hope_user:hope_password@localhost:5432/hope_jobs",
        storage="postgres",
    )
    try:
        assert isinstance(store, PostgresJobStore)
    finally:
        store.close()


@pytest.mark.unit
def test_create_job_store_rejects_unknown_scheme():
    with pytest.raises(JobStoreError, match="Unsupported DATABASE_URL scheme"):
        create_job_store("mysql://localhost/hope")


@pytest.mark.unit
def test_create_job_store_normalizes_postgresql_driver():
    store = create_job_store(
        "postgresql://hope_user:hope_password@localhost:5432/hope_jobs",
        storage="postgres",
    )
    try:
        assert isinstance(store, PostgresJobStore)
        assert store.database_url.startswith("postgresql+psycopg://")
    finally:
        store.close()


class _RecordingStore:
    """Minimal JobStore used to prove run_mvp depends on the protocol."""

    def __init__(self, database_url):
        self.database_url = database_url
        self.events: list[str] = []
        self.persisted_run_id: str | None = None

    def preflight(self) -> None:
        self.events.append("preflight")

    def persist_pipeline_run(self, *, run_id, **_kwargs) -> None:
        self.events.append("persist")
        self.persisted_run_id = run_id

    def table_counts(self, *table_names):
        return {name: 0 for name in table_names}

    def close(self) -> None:
        self.events.append("close")


@pytest.mark.unit
def test_run_mvp_uses_injected_store_factory(tmp_path):
    from pathlib import Path

    from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline

    created: list[_RecordingStore] = []

    def factory(database_url):
        store = _RecordingStore(database_url)
        created.append(store)
        return store

    run_mvp_pipeline(
        source_name="kelleylink_excel",
        input_path=Path("data/sample_12twenty_export.xlsx"),
        profiles_path=None,
        output_path=tmp_path / "mvp_jobs.csv",
        store_factory=factory,
    )

    assert len(created) == 1
    assert created[0].events == ["preflight", "persist", "close"]
    assert created[0].persisted_run_id is not None

import pytest

from hope_job_agent.storage import (
    JobStore,
    JobStoreError,
    SQLiteJobStore,
    SQLiteJobStoreError,
    create_job_store,
)


def test_create_job_store_returns_sqlite_for_empty_url():
    store = create_job_store("")
    try:
        assert isinstance(store, SQLiteJobStore)
        assert isinstance(store, JobStore)
    finally:
        store.close()


def test_create_job_store_returns_sqlite_for_memory_url():
    store = create_job_store("sqlite:///:memory:")
    try:
        assert isinstance(store, SQLiteJobStore)
    finally:
        store.close()


def test_create_job_store_flags_postgres_as_unimplemented_dropin():
    with pytest.raises(
        JobStoreError, match="PostgreSQL persistence is not implemented"
    ):
        create_job_store("postgresql://user:pass@localhost:5432/hope")


def test_create_job_store_rejects_unknown_scheme():
    with pytest.raises(JobStoreError, match="Unsupported DATABASE_URL scheme"):
        create_job_store("mysql://localhost/hope")


def test_sqlite_error_is_a_job_store_error():
    assert issubclass(SQLiteJobStoreError, JobStoreError)


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

"""Storage seam for pipeline persistence.

`run_mvp` depends on the :class:`JobStore` protocol rather than a concrete
backend, and constructs stores through :func:`create_job_store`. This keeps the
current local SQLite backend in place while making PostgreSQL a drop-in for
shared/production use.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hope_job_agent.config.database import resolve_database_url
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile


class JobStoreError(RuntimeError):
    """Raised when persistence cannot be configured or completed."""


@runtime_checkable
class JobStore(Protocol):
    """Minimal persistence contract the pipeline depends on."""

    def preflight(self) -> None:
        """Validate connectivity/schema before a run persists anything."""
        ...

    def persist_pipeline_run(
        self,
        *,
        run_id: str,
        run_type: str,
        source: str,
        summary: Mapping[str, Any],
        normalized_jobs: Sequence[JobPosting],
        valid_jobs: Sequence[JobPosting],
        deduped_jobs: Sequence[JobPosting],
        ranked_matches: Sequence[tuple[StudentProfile, Sequence[JobMatch]]],
        input_path: Path | str | None = None,
        profiles_path: Path | str | None = None,
        output_path: Path | str | None = None,
    ) -> None:
        """Persist one completed pipeline run and its job/match state."""
        ...

    def table_counts(self, *table_names: str) -> dict[str, int]:
        """Return row counts for the named tables (diagnostics)."""
        ...

    def close(self) -> None:
        """Release any underlying connection/resources."""
        ...


def create_job_store(
    database_url: str | None = None,
    *,
    storage: str = "auto",
) -> JobStore:
    """Build a :class:`JobStore` for the configured persistence mode.

    ``storage`` values:

    * ``auto`` — PostgreSQL when ``database_url``/``DATABASE_URL`` is postgres,
      otherwise SQLite (empty URL -> default file).
    * ``sqlite`` — local SQLite backend.
    * ``memory`` — in-memory store (no database).
    * ``postgres`` — PostgreSQL via repositories + pgvector schema.
    """

    mode = storage.strip().casefold()
    try:
        resolved = resolve_database_url(
            database_url,
            storage=mode if mode != "auto" else "auto",
        )
    except ValueError as exc:
        raise JobStoreError(str(exc)) from exc

    if mode == "memory":
        from hope_job_agent.storage.memory_store import MemoryJobStore

        return MemoryJobStore(database_url=resolved or "memory://")

    scheme = resolved.split("://", 1)[0].lower() if "://" in resolved else ""

    if mode == "postgres" or scheme.startswith("postgres"):
        from hope_job_agent.storage.postgres_store import PostgresJobStore

        return PostgresJobStore(resolved, storage="postgres")

    if resolved == "" or scheme == "sqlite":
        from hope_job_agent.storage.sqlite_store import SQLiteJobStore

        return SQLiteJobStore(resolved or None)

    raise JobStoreError(
        f"Unsupported DATABASE_URL scheme for persistence: {database_url!r}"
    )

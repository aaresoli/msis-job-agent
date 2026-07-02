"""Storage seam for pipeline persistence.

`run_mvp` depends on the :class:`JobStore` protocol rather than a concrete
backend, and constructs stores through :func:`create_job_store`. This keeps the
current local SQLite backend in place while making an alternative backend (for
example a managed PostgreSQL instance for shared/production use) a drop-in:
implement the protocol and register it in the factory. No behavior changes for
SQLite users.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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


def create_job_store(database_url: str | None) -> JobStore:
    """Build a :class:`JobStore` for the configured ``database_url``.

    Empty and ``sqlite://`` URLs return the local SQLite backend. A
    ``postgres://`` URL is recognized as the intended drop-in point but is not
    implemented yet; the error explains how to register a backend.
    """

    value = (database_url or "").strip()
    scheme = value.split("://", 1)[0].lower() if "://" in value else ""

    if value == "" or scheme == "sqlite":
        from hope_job_agent.storage.sqlite_store import SQLiteJobStore

        return SQLiteJobStore(database_url)

    if scheme in {"postgres", "postgresql"}:
        raise JobStoreError(
            "PostgreSQL persistence is not implemented yet. Implement the "
            "JobStore protocol and register it in create_job_store() as a "
            "drop-in replacement, or set DATABASE_URL to a sqlite URL for "
            "local runs."
        )

    raise JobStoreError(
        f"Unsupported DATABASE_URL scheme for persistence: {database_url!r}"
    )

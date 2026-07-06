"""Source run audit repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import SourceRun


class SourceRunRepository:
    """Audit log for ingestion runs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(
        self,
        source_name: str,
        *,
        run_id: uuid.UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceRun:
        """Create a running source run record."""

        resolved_id = _coerce_uuid(run_id) or uuid.uuid4()
        run = SourceRun(
            id=resolved_id,
            source_name=source_name,
            run_status="running",
            started_at=datetime.now(UTC),
            metadata_json=metadata,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def finish_run(
        self,
        run_id: uuid.UUID | str,
        *,
        summary: dict[str, Any],
    ) -> SourceRun:
        """Mark a run successful or partially successful."""

        run = self._require_run(run_id)
        run.run_status = "partial_success" if summary.get("errors") else "success"
        run.finished_at = datetime.now(UTC)
        run.jobs_fetched = int(summary.get("raw_count", 0))
        run.jobs_inserted = int(summary.get("jobs_inserted", 0))
        run.jobs_updated = int(summary.get("jobs_updated", 0))
        run.jobs_skipped = int(summary.get("jobs_skipped", 0))
        run.jobs_deduped = int(summary.get("duplicate_count", 0))
        run.errors_count = len(summary.get("errors") or [])
        run.metadata_json = {**(run.metadata_json or {}), **summary}
        self._session.flush()
        return run

    def fail_run(self, run_id: uuid.UUID | str, error: str) -> SourceRun:
        """Mark a run failed."""

        run = self._require_run(run_id)
        run.run_status = "failed"
        run.finished_at = datetime.now(UTC)
        run.errors_count = max(int(run.errors_count or 0), 1)
        run.error_summary = error
        self._session.flush()
        return run

    def list_recent_runs(
        self,
        *,
        source: str | None = None,
        limit: int = 20,
    ) -> list[SourceRun]:
        """Return recent source runs."""

        stmt = select(SourceRun).order_by(SourceRun.started_at.desc()).limit(limit)
        if source:
            stmt = stmt.where(SourceRun.source_name == source)
        return list(self._session.scalars(stmt))

    def _require_run(self, run_id: uuid.UUID | str) -> SourceRun:
        resolved_id = _coerce_uuid(run_id)
        run = self._session.get(SourceRun, resolved_id)
        if run is None:
            raise LookupError(f"Source run not found: {run_id}")
        return run


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))

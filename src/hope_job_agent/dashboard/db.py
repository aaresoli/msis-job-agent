"""Read-only SQLite access for the demo dashboard.

The dashboard never writes: it opens the pipeline's SQLite store in read-only
mode, caches parsed jobs keyed by the database file's mtime, and degrades to
the last cached snapshot (or an empty one) when the file is missing or locked
by a concurrent pipeline run.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hope_job_agent.models.job import JobPosting

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DashboardSnapshot:
    """One consistent read of the store used to answer API requests."""

    entries: list[tuple[str, JobPosting]] = field(default_factory=list)
    latest_run: dict[str, Any] | None = None
    db_exists: bool = False


class JobRepository:
    """Mtime-cached, read-only view over the pipeline SQLite store."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._cached: DashboardSnapshot | None = None
        self._cached_mtime_ns: int | None = None

    def load(self) -> DashboardSnapshot:
        """Return the current snapshot, re-reading only when the file changed."""

        try:
            mtime_ns = os.stat(self.db_path).st_mtime_ns
        except OSError:
            self._cached = None
            self._cached_mtime_ns = None
            return DashboardSnapshot(db_exists=False)

        if self._cached is not None and self._cached_mtime_ns == mtime_ns:
            return self._cached

        try:
            snapshot = self._read_snapshot()
        except sqlite3.Error as exc:
            LOGGER.warning(
                "Dashboard could not read %s (%s); serving %s data",
                self.db_path,
                exc,
                "cached" if self._cached is not None else "empty",
            )
            return self._cached or DashboardSnapshot(db_exists=True)

        self._cached = snapshot
        self._cached_mtime_ns = mtime_ns
        return snapshot

    def _read_snapshot(self) -> DashboardSnapshot:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            entries = self._load_jobs(conn)
            latest_run = self._load_latest_run(conn)
        return DashboardSnapshot(
            entries=entries,
            latest_run=latest_run,
            db_exists=True,
        )

    @staticmethod
    def _load_jobs(conn: sqlite3.Connection) -> list[tuple[str, JobPosting]]:
        rows = conn.execute(
            "SELECT job_key, job_json FROM deduped_jobs ORDER BY last_seen_at DESC"
        ).fetchall()
        entries: list[tuple[str, JobPosting]] = []
        for row in rows:
            try:
                job = JobPosting.model_validate_json(row["job_json"])
            except ValidationError as exc:
                LOGGER.warning(
                    "Dashboard skipped unparseable job %s: %s",
                    row["job_key"],
                    exc.errors()[0].get("msg") if exc.errors() else exc,
                )
                continue
            entries.append((str(row["job_key"]), job))
        return entries

    @staticmethod
    def _load_latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT run_id, source, completed_at, unique_count, runtime_seconds
            FROM pipeline_runs
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "source": str(row["source"]),
            "completed_at": str(row["completed_at"]),
            "unique_count": int(row["unique_count"]),
            "runtime_seconds": row["runtime_seconds"],
        }

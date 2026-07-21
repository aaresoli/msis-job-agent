"""Read-only store access for the demo dashboard.

The dashboard never writes. Two backends share one ``load()`` contract:

* :class:`JobRepository` opens the pipeline's SQLite store in read-only mode
  and caches parsed jobs keyed by the database file's mtime.
* :class:`PostgresJobRepository` reads the platform ``job_postings`` table and
  caches for a short TTL, since there is no mtime to watch.

Both degrade to the last cached snapshot (or an empty one) when the store is
missing, locked by a concurrent pipeline run, or unreachable.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from hope_job_agent.db.models import JobPostingRecord, SourceRun
from hope_job_agent.db.platform_models import MarketPost, MarketSignal
from hope_job_agent.db.session import create_db_engine, create_session_factory
from hope_job_agent.models.job import JobPosting

from .posts_service import MarketPostView, PostSignalView

LOGGER = logging.getLogger(__name__)

POSTGRES_CACHE_TTL_SECONDS = 15.0

# Cap the working set the Posts view loads into memory per snapshot.
_MAX_POSTS = 500
_MAX_SIGNALS = 300


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
        row = conn.execute("""
            SELECT run_id, source, completed_at, unique_count, runtime_seconds
            FROM pipeline_runs
            ORDER BY completed_at DESC
            LIMIT 1
            """).fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "source": str(row["source"]),
            "completed_at": str(row["completed_at"]),
            "unique_count": int(row["unique_count"]),
            "runtime_seconds": row["runtime_seconds"],
        }


class PostgresJobRepository:
    """TTL-cached, read-only view over the platform ``job_postings`` table."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        ttl_seconds: float = POSTGRES_CACHE_TTL_SECONDS,
    ) -> None:
        self._engine = create_db_engine(database_url, storage="postgres")
        self._session_factory = create_session_factory(self._engine)
        self._ttl_seconds = ttl_seconds
        self._cached: DashboardSnapshot | None = None
        self._cached_at: float | None = None
        # Reported by /api/health; the password is stripped from the URL.
        self.db_path = self._engine.url.render_as_string(hide_password=True)

    def load(self) -> DashboardSnapshot:
        """Return the current snapshot, re-querying only after the TTL lapses."""

        now = time.monotonic()
        if (
            self._cached is not None
            and self._cached_at is not None
            and now - self._cached_at < self._ttl_seconds
        ):
            return self._cached

        try:
            snapshot = self._read_snapshot()
        except SQLAlchemyError as exc:
            LOGGER.warning(
                "Dashboard could not read %s (%s); serving %s data",
                self.db_path,
                exc,
                "cached" if self._cached is not None else "empty",
            )
            return self._cached or DashboardSnapshot(db_exists=False)

        self._cached = snapshot
        self._cached_at = now
        return snapshot

    def _read_snapshot(self) -> DashboardSnapshot:
        with self._session_factory() as session:
            entries = self._load_jobs(session)
            latest_run = self._load_latest_run(session)
        return DashboardSnapshot(
            entries=entries,
            latest_run=latest_run,
            db_exists=True,
        )

    @staticmethod
    def _load_jobs(session) -> list[tuple[str, JobPosting]]:  # noqa: ANN001
        rows = session.execute(
            select(JobPostingRecord.id, JobPostingRecord.job_json)
            .where(
                JobPostingRecord.status == "active",
                JobPostingRecord.job_json.is_not(None),
            )
            .order_by(JobPostingRecord.last_seen_at.desc())
        ).all()
        entries: list[tuple[str, JobPosting]] = []
        for job_id, job_json in rows:
            try:
                job = JobPosting.model_validate(job_json)
            except ValidationError as exc:
                LOGGER.warning(
                    "Dashboard skipped unparseable job %s: %s",
                    job_id,
                    exc.errors()[0].get("msg") if exc.errors() else exc,
                )
                continue
            entries.append((str(job_id), job))
        return entries

    @staticmethod
    def _load_latest_run(session) -> dict[str, Any] | None:  # noqa: ANN001
        run = session.scalar(
            select(SourceRun)
            .where(SourceRun.finished_at.is_not(None))
            .order_by(SourceRun.finished_at.desc())
            .limit(1)
        )
        if run is None:
            return None
        summary = (run.metadata_json or {}).get("summary") or {}
        unique_count = summary.get("unique_count")
        if unique_count is None:
            unique_count = run.jobs_inserted + run.jobs_updated
        return {
            "run_id": str(run.id),
            "source": run.source_name,
            "completed_at": run.finished_at.isoformat(),
            "unique_count": int(unique_count),
            "runtime_seconds": summary.get("runtime_seconds"),
        }


@dataclass(frozen=True)
class PostsSnapshot:
    """One consistent read of the ``market_posts`` store for the Posts view."""

    posts: list[MarketPostView] = field(default_factory=list)
    latest_post_at: datetime | None = None
    db_exists: bool = False


class NullPostRepository:
    """Empty posts backend used when the dashboard runs on the SQLite store.

    Posts, LLM signals, and the market-pulse worker are platform/Postgres
    features, so the offline SQLite demo has no posts to serve; the Posts tab
    then shows a graceful empty state.
    """

    store_label = "sqlite (posts require the platform Postgres DB)"

    def load(self) -> PostsSnapshot:
        return PostsSnapshot(db_exists=False)


class PostgresPostRepository:
    """TTL-cached, read-only view over ``market_posts`` + cited signals."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        ttl_seconds: float = POSTGRES_CACHE_TTL_SECONDS,
    ) -> None:
        self._engine = create_db_engine(database_url, storage="postgres")
        self._session_factory = create_session_factory(self._engine)
        self._ttl_seconds = ttl_seconds
        self._cached: PostsSnapshot | None = None
        self._cached_at: float | None = None
        self.store_label = self._engine.url.render_as_string(hide_password=True)

    def load(self) -> PostsSnapshot:
        now = time.monotonic()
        if (
            self._cached is not None
            and self._cached_at is not None
            and now - self._cached_at < self._ttl_seconds
        ):
            return self._cached
        try:
            snapshot = self._read_snapshot()
        except SQLAlchemyError as exc:
            LOGGER.warning(
                "Dashboard could not read market_posts (%s); serving %s data",
                exc,
                "cached" if self._cached is not None else "empty",
            )
            return self._cached or PostsSnapshot(db_exists=False)
        self._cached = snapshot
        self._cached_at = now
        return snapshot

    def _read_snapshot(self) -> PostsSnapshot:
        with self._session_factory() as session:
            signals_by_post = self._load_signals(session)
            posts = self._load_posts(session, signals_by_post)
        latest = next(
            (post.published_at for post in posts if post.published_at is not None),
            None,
        )
        return PostsSnapshot(posts=posts, latest_post_at=latest, db_exists=True)

    @staticmethod
    def _load_signals(session) -> dict[str, list[PostSignalView]]:  # noqa: ANN001
        rows = session.scalars(
            select(MarketSignal)
            .order_by(MarketSignal.created_at.desc())
            .limit(_MAX_SIGNALS)
        ).all()
        by_post: dict[str, list[PostSignalView]] = {}
        for signal in rows:
            view = PostSignalView(
                topic=signal.topic,
                summary=signal.summary,
                company_name=signal.company_name,
                role_tags=list(signal.role_tags or []),
                confidence=signal.confidence,
            )
            for post_id in signal.citation_post_ids or []:
                by_post.setdefault(str(post_id), []).append(view)
        return by_post

    @staticmethod
    def _load_posts(  # noqa: ANN001
        session,
        signals_by_post: dict[str, list[PostSignalView]],
    ) -> list[MarketPostView]:
        rows = session.scalars(
            select(MarketPost)
            .order_by(MarketPost.published_at.desc().nullslast())
            .limit(_MAX_POSTS)
        ).all()
        posts: list[MarketPostView] = []
        for row in rows:
            relevance = (row.raw_metadata or {}).get("msis_relevance") or {}
            post_key = str(row.id)
            posts.append(
                MarketPostView(
                    post_key=post_key,
                    author_name=row.author_name,
                    company_name=row.company_name,
                    content=row.content,
                    source_url=row.source_url,
                    published_at=row.published_at,
                    relevance_score=_as_float(relevance.get("score")),
                    matched_keywords=list(relevance.get("matched_keywords") or []),
                    concentration_hints=list(
                        relevance.get("concentration_hints") or []
                    ),
                    career_stage=relevance.get("career_stage"),
                    signals=signals_by_post.get(post_key, []),
                )
            )
        return posts


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

"""Read-only snapshot access for the discovery views.

Both repositories read the platform Postgres tables and never write. They
reconstruct full :class:`~hope_job_agent.models.job.JobPosting` objects from the
``job_postings.job_json`` payload, which is why that column exists: the
relational columns are a flattened projection that drops discovery-facing
fields such as ``career_track`` and ``role_tags``.

Snapshots are cached for a short TTL and degrade to the last good one (or an
empty one) when the database is unreachable, so a blip never surfaces as an
error page.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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
class JobsSnapshot:
    """One consistent read of the store used to answer API requests."""

    entries: list[tuple[str, JobPosting]] = field(default_factory=list)
    latest_run: dict[str, Any] | None = None
    db_exists: bool = False


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
        self._cached: JobsSnapshot | None = None
        self._cached_at: float | None = None
        # Reported by /api/health; the password is stripped from the URL.
        self.db_path = self._engine.url.render_as_string(hide_password=True)

    def load(self) -> JobsSnapshot:
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
                "Discovery could not read %s (%s); serving %s data",
                self.db_path,
                exc,
                "cached" if self._cached is not None else "empty",
            )
            return self._cached or JobsSnapshot(db_exists=False)

        self._cached = snapshot
        self._cached_at = now
        return snapshot

    def _read_snapshot(self) -> JobsSnapshot:
        with self._session_factory() as session:
            entries = self._load_jobs(session)
            latest_run = self._load_latest_run(session)
        return JobsSnapshot(
            entries=entries,
            latest_run=latest_run,
            db_exists=True,
        )

    @staticmethod
    def _load_jobs(session: Session) -> list[tuple[str, JobPosting]]:
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
                    "Discovery skipped unparseable job %s: %s",
                    job_id,
                    exc.errors()[0].get("msg") if exc.errors() else exc,
                )
                continue
            entries.append((str(job_id), job))
        return entries

    @staticmethod
    def _load_latest_run(session: Session) -> dict[str, Any] | None:
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
            # The query filters finished_at IS NOT NULL.
            "completed_at": run.finished_at.isoformat() if run.finished_at else "",
            "unique_count": int(unique_count),
            "runtime_seconds": summary.get("runtime_seconds"),
        }


@dataclass(frozen=True)
class PostsSnapshot:
    """One consistent read of the ``market_posts`` store for the Posts view."""

    posts: list[MarketPostView] = field(default_factory=list)
    latest_post_at: datetime | None = None
    db_exists: bool = False


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
                "Discovery could not read market_posts (%s); serving %s data",
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
    def _load_signals(session: Session) -> dict[str, list[PostSignalView]]:
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
    def _load_posts(
        session: Session,
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

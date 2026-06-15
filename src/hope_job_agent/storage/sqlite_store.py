"""SQLite persistence for normalized jobs, matches, and pipeline history."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from hope_job_agent.classification.classifier import CLASSIFIER_VERSION
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.scoring.ranker import RANKER_VERSION
from hope_job_agent.utils.hashing import stable_hash
from hope_job_agent.utils.url import canonicalize_url

DEFAULT_DATABASE_PATH = Path("data/hope_job_agent.sqlite3")
_SQLITE_MEMORY_URL = "sqlite:///:memory:"
_SQLITE_FILE_PREFIX = "sqlite:///"


class SQLiteJobStoreError(RuntimeError):
    """Raised when persistence cannot be configured or completed."""


@dataclass(frozen=True)
class SQLiteDatabase:
    """Resolved SQLite connection target."""

    database: str
    path: Path | None


def resolve_sqlite_database(database_url: str | None) -> SQLiteDatabase:
    """Resolve a supported SQLite database URL into a sqlite3 target."""

    value = (database_url or "").strip()
    if not value:
        return SQLiteDatabase(
            database=str(DEFAULT_DATABASE_PATH),
            path=DEFAULT_DATABASE_PATH,
        )

    if value == _SQLITE_MEMORY_URL:
        return SQLiteDatabase(database=":memory:", path=None)

    if value.startswith(_SQLITE_FILE_PREFIX):
        raw_path = unquote(value[len(_SQLITE_FILE_PREFIX) :])
        if raw_path == ":memory:":
            return SQLiteDatabase(database=":memory:", path=None)
        if not raw_path:
            raise SQLiteJobStoreError("SQLite DATABASE_URL must include a file path")
        path = Path(raw_path)
        return SQLiteDatabase(database=str(path), path=path)

    raise SQLiteJobStoreError(
        "Only empty DATABASE_URL, sqlite:///path/to.db, and sqlite:///:memory: "
        "are supported for local persistence"
    )


def canonical_job_url(job: JobPosting) -> str | None:
    """Return the canonical URL identity for a job, when one is available."""

    url = str(getattr(job, "url", "") or "").strip()
    if not url:
        return None
    return canonicalize_url(url)


def source_job_identity(job: JobPosting) -> str | None:
    """Return the normalized source-provided job identity, when present."""

    raw_metadata = getattr(job, "raw_metadata", {}) or {}
    source_job_id = getattr(job, "source_job_id", None) or raw_metadata.get(
        "source_job_id"
    )
    source = str(getattr(job, "source", "") or "").strip().casefold()
    value = str(source_job_id or "").strip().casefold()
    if not source or not value:
        return None
    return f"{source}:{value}"


def content_signature(job: JobPosting) -> str:
    """Return a stable content signature used as the weakest job identity."""

    description = " ".join(str(getattr(job, "description", "") or "").split())
    parts = [
        str(getattr(job, "title", "") or "").strip().casefold(),
        str(getattr(job, "company", "") or "").strip().casefold(),
        str(getattr(job, "location", "") or "").strip().casefold(),
        description.casefold(),
    ]
    return stable_hash("||".join(parts))


def student_key(profile: StudentProfile) -> str:
    """Return the stable student key used in ranking and match tables."""

    if profile.student_id and profile.student_id.strip():
        return profile.student_id.strip()
    return stable_hash(profile.name)[:10]


class SQLiteJobStore:
    """SQLite-backed store with idempotent upserts for pipeline artifacts."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database = resolve_sqlite_database(database_url)
        self._connection: sqlite3.Connection | None = None

    def close(self) -> None:
        """Close the underlying sqlite3 connection, if it is open."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def preflight(self) -> None:
        """Verify the SQLite target can be opened and initialized."""

        try:
            self._connect()
        except sqlite3.Error as exc:
            raise SQLiteJobStoreError(f"SQLite persistence failed: {exc}") from exc

    def table_counts(self, *table_names: str) -> dict[str, int]:
        """Return row counts for test and diagnostics tables."""

        conn = self._connect()
        counts: dict[str, int] = {}
        for table_name in table_names:
            if not table_name.replace("_", "").isalnum():
                raise SQLiteJobStoreError(f"Unsafe table name: {table_name}")
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
            counts[table_name] = int(row["count"])
        return counts

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
        """Persist one completed pipeline run and its current job/match state."""

        now = _utc_now()
        valid_normalized_keys = {_normalized_job_key(job) for job in valid_jobs}

        try:
            with self._transaction() as conn:
                self._upsert_pipeline_run(
                    conn=conn,
                    run_id=run_id,
                    run_type=run_type,
                    source=source,
                    summary=summary,
                    normalized_jobs=normalized_jobs,
                    valid_jobs=valid_jobs,
                    deduped_jobs=deduped_jobs,
                    ranked_matches=ranked_matches,
                    input_path=input_path,
                    profiles_path=profiles_path,
                    output_path=output_path,
                    now=now,
                )

                for job in normalized_jobs:
                    validation_status = (
                        "valid"
                        if _normalized_job_key(job) in valid_normalized_keys
                        else "invalid"
                    )
                    self._upsert_normalized_job(
                        conn=conn,
                        job=job,
                        validation_status=validation_status,
                        run_id=run_id,
                        now=now,
                    )

                for job in deduped_jobs:
                    job_key = self._upsert_deduped_job(
                        conn=conn,
                        job=job,
                        run_id=run_id,
                        now=now,
                    )
                    self._upsert_classification_result(
                        conn=conn,
                        job=job,
                        job_key=job_key,
                        run_id=run_id,
                        now=now,
                    )

                for profile, matches in ranked_matches:
                    profile_key = student_key(profile)
                    for rank_position, match in enumerate(matches, start=1):
                        resolved_job_key = self._resolve_job_key(conn, match.job)
                        if resolved_job_key is None:
                            resolved_job_key = self._upsert_deduped_job(
                                conn=conn,
                                job=match.job,
                                run_id=run_id,
                                now=now,
                            )
                        self._upsert_ranking_score(
                            conn=conn,
                            profile=profile,
                            profile_key=profile_key,
                            match=match,
                            job_key=resolved_job_key,
                            rank_position=rank_position,
                            run_id=run_id,
                            now=now,
                        )
                        self._upsert_match_history(
                            conn=conn,
                            profile=profile,
                            profile_key=profile_key,
                            match=match,
                            job_key=resolved_job_key,
                            run_id=run_id,
                            now=now,
                        )
        except sqlite3.Error as exc:
            raise SQLiteJobStoreError(f"SQLite persistence failed: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            if self.database.path is not None:
                self.database.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.database.database)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._initialize(self._connection)
        return self._connection

    @contextmanager
    def _transaction(self) -> Any:
        conn = self._connect()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _initialize(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                source TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT NOT NULL,
                input_path TEXT,
                profiles_path TEXT,
                output_path TEXT,
                raw_count INTEGER NOT NULL DEFAULT 0,
                normalized_count INTEGER NOT NULL DEFAULT 0,
                valid_count INTEGER NOT NULL DEFAULT 0,
                invalid_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                unique_count INTEGER NOT NULL DEFAULT 0,
                classified_count INTEGER NOT NULL DEFAULT 0,
                profile_count INTEGER NOT NULL DEFAULT 0,
                active_profile_count INTEGER NOT NULL DEFAULT 0,
                total_ranked_matches INTEGER NOT NULL DEFAULT 0,
                warnings_json TEXT NOT NULL,
                errors_json TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                runtime_seconds REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS normalized_jobs (
                normalized_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_job_id TEXT,
                canonical_url TEXT,
                content_signature TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                job_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                last_run_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deduped_jobs (
                job_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_job_id TEXT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                canonical_url TEXT,
                content_signature TEXT NOT NULL,
                job_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                last_run_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_identities (
                identity_type TEXT NOT NULL,
                identity_value TEXT NOT NULL,
                job_key TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (identity_type, identity_value),
                FOREIGN KEY (job_key) REFERENCES deduped_jobs(job_key)
            );

            CREATE INDEX IF NOT EXISTS idx_job_identities_job_key
                ON job_identities(job_key);

            CREATE TABLE IF NOT EXISTS classification_results (
                job_key TEXT NOT NULL,
                classifier_version TEXT NOT NULL,
                role_tags_json TEXT NOT NULL,
                concentration_tags_json TEXT NOT NULL,
                classified_job_json TEXT NOT NULL,
                first_classified_at TEXT NOT NULL,
                last_classified_at TEXT NOT NULL,
                times_classified INTEGER NOT NULL DEFAULT 1,
                last_run_id TEXT NOT NULL,
                PRIMARY KEY (job_key, classifier_version),
                FOREIGN KEY (job_key) REFERENCES deduped_jobs(job_key)
            );

            CREATE TABLE IF NOT EXISTS ranking_scores (
                student_key TEXT NOT NULL,
                profile_version INTEGER NOT NULL,
                job_key TEXT NOT NULL,
                ranker_version TEXT NOT NULL,
                score REAL NOT NULL,
                rank_position INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                first_scored_at TEXT NOT NULL,
                last_scored_at TEXT NOT NULL,
                times_scored INTEGER NOT NULL DEFAULT 1,
                last_run_id TEXT NOT NULL,
                PRIMARY KEY (
                    student_key,
                    profile_version,
                    job_key,
                    ranker_version
                ),
                FOREIGN KEY (job_key) REFERENCES deduped_jobs(job_key)
            );

            CREATE TABLE IF NOT EXISTS match_history (
                match_key TEXT PRIMARY KEY,
                student_key TEXT NOT NULL,
                profile_version INTEGER NOT NULL,
                job_key TEXT NOT NULL,
                ranker_version TEXT NOT NULL,
                first_run_id TEXT NOT NULL,
                last_run_id TEXT NOT NULL,
                first_matched_at TEXT NOT NULL,
                last_matched_at TEXT NOT NULL,
                latest_score REAL NOT NULL,
                reasons_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                times_matched INTEGER NOT NULL DEFAULT 1,
                UNIQUE (
                    student_key,
                    profile_version,
                    job_key,
                    ranker_version
                ),
                FOREIGN KEY (job_key) REFERENCES deduped_jobs(job_key)
            );
            """)

    def _upsert_pipeline_run(
        self,
        *,
        conn: sqlite3.Connection,
        run_id: str,
        run_type: str,
        source: str,
        summary: Mapping[str, Any],
        normalized_jobs: Sequence[JobPosting],
        valid_jobs: Sequence[JobPosting],
        deduped_jobs: Sequence[JobPosting],
        ranked_matches: Sequence[tuple[StudentProfile, Sequence[JobMatch]]],
        input_path: Path | str | None,
        profiles_path: Path | str | None,
        output_path: Path | str | None,
        now: str,
    ) -> None:
        total_ranked_matches = sum(len(matches) for _profile, matches in ranked_matches)
        params = {
            "run_id": run_id,
            "run_type": run_type,
            "source": source,
            "started_at": _optional_text(summary.get("timestamp")),
            "completed_at": now,
            "input_path": _optional_path(input_path)
            or _optional_text(summary.get("input_path")),
            "profiles_path": _optional_path(profiles_path)
            or _optional_text(summary.get("profiles_path")),
            "output_path": _optional_path(output_path)
            or _optional_text(summary.get("output_path")),
            "raw_count": _summary_int(summary, "raw_count", len(normalized_jobs)),
            "normalized_count": _summary_int(
                summary,
                "normalized_count",
                len(normalized_jobs),
            ),
            "valid_count": _summary_int(summary, "valid_count", len(valid_jobs)),
            "invalid_count": _summary_int(
                summary,
                "invalid_count",
                max(len(normalized_jobs) - len(valid_jobs), 0),
            ),
            "duplicate_count": _summary_int(
                summary,
                "duplicate_count",
                max(len(valid_jobs) - len(deduped_jobs), 0),
            ),
            "unique_count": _summary_int(summary, "unique_count", len(deduped_jobs)),
            "classified_count": _summary_int(
                summary,
                "classified_count",
                len(deduped_jobs),
            ),
            "profile_count": _summary_int(
                summary,
                "profile_count",
                len(ranked_matches),
            ),
            "active_profile_count": _summary_int(
                summary,
                "active_profile_count",
                len(ranked_matches),
            ),
            "total_ranked_matches": _summary_int(
                summary,
                "total_ranked_matches",
                total_ranked_matches,
            ),
            "warnings_json": _json_dumps(summary.get("warnings", [])),
            "errors_json": _json_dumps(summary.get("errors", [])),
            "summary_json": _json_dumps(dict(summary)),
            "runtime_seconds": summary.get("runtime_seconds"),
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO pipeline_runs (
                run_id,
                run_type,
                source,
                started_at,
                completed_at,
                input_path,
                profiles_path,
                output_path,
                raw_count,
                normalized_count,
                valid_count,
                invalid_count,
                duplicate_count,
                unique_count,
                classified_count,
                profile_count,
                active_profile_count,
                total_ranked_matches,
                warnings_json,
                errors_json,
                summary_json,
                runtime_seconds,
                created_at,
                updated_at
            )
            VALUES (
                :run_id,
                :run_type,
                :source,
                :started_at,
                :completed_at,
                :input_path,
                :profiles_path,
                :output_path,
                :raw_count,
                :normalized_count,
                :valid_count,
                :invalid_count,
                :duplicate_count,
                :unique_count,
                :classified_count,
                :profile_count,
                :active_profile_count,
                :total_ranked_matches,
                :warnings_json,
                :errors_json,
                :summary_json,
                :runtime_seconds,
                :created_at,
                :updated_at
            )
            ON CONFLICT(run_id) DO UPDATE SET
                run_type = excluded.run_type,
                source = excluded.source,
                completed_at = excluded.completed_at,
                input_path = excluded.input_path,
                profiles_path = excluded.profiles_path,
                output_path = excluded.output_path,
                raw_count = excluded.raw_count,
                normalized_count = excluded.normalized_count,
                valid_count = excluded.valid_count,
                invalid_count = excluded.invalid_count,
                duplicate_count = excluded.duplicate_count,
                unique_count = excluded.unique_count,
                classified_count = excluded.classified_count,
                profile_count = excluded.profile_count,
                active_profile_count = excluded.active_profile_count,
                total_ranked_matches = excluded.total_ranked_matches,
                warnings_json = excluded.warnings_json,
                errors_json = excluded.errors_json,
                summary_json = excluded.summary_json,
                runtime_seconds = excluded.runtime_seconds,
                updated_at = excluded.updated_at
            """,
            params,
        )

    def _upsert_normalized_job(
        self,
        *,
        conn: sqlite3.Connection,
        job: JobPosting,
        validation_status: str,
        run_id: str,
        now: str,
    ) -> None:
        params = {
            "normalized_key": _normalized_job_key(job),
            "source": str(getattr(job, "source", "") or ""),
            "source_job_id": _source_job_id(job),
            "canonical_url": canonical_job_url(job),
            "content_signature": content_signature(job),
            "validation_status": validation_status,
            "job_json": _json_dumps(job.model_dump(mode="json")),
            "first_seen_at": now,
            "last_seen_at": now,
            "last_run_id": run_id,
        }
        conn.execute(
            """
            INSERT INTO normalized_jobs (
                normalized_key,
                source,
                source_job_id,
                canonical_url,
                content_signature,
                validation_status,
                job_json,
                first_seen_at,
                last_seen_at,
                last_run_id
            )
            VALUES (
                :normalized_key,
                :source,
                :source_job_id,
                :canonical_url,
                :content_signature,
                :validation_status,
                :job_json,
                :first_seen_at,
                :last_seen_at,
                :last_run_id
            )
            ON CONFLICT(normalized_key) DO UPDATE SET
                source = excluded.source,
                source_job_id = excluded.source_job_id,
                canonical_url = excluded.canonical_url,
                content_signature = excluded.content_signature,
                validation_status = excluded.validation_status,
                job_json = excluded.job_json,
                last_seen_at = excluded.last_seen_at,
                seen_count = normalized_jobs.seen_count + 1,
                last_run_id = excluded.last_run_id
            """,
            params,
        )

    def _upsert_deduped_job(
        self,
        *,
        conn: sqlite3.Connection,
        job: JobPosting,
        run_id: str,
        now: str,
    ) -> str:
        identities = _job_identities(job)
        job_key = self._resolve_job_key_from_identities(conn, identities)
        if job_key is None:
            job_key = _new_job_key(identities)

        params = {
            "job_key": job_key,
            "source": str(getattr(job, "source", "") or ""),
            "source_job_id": _source_job_id(job),
            "title": str(getattr(job, "title", "") or ""),
            "company": str(getattr(job, "company", "") or ""),
            "location": str(getattr(job, "location", "") or ""),
            "canonical_url": canonical_job_url(job),
            "content_signature": content_signature(job),
            "job_json": _json_dumps(job.model_dump(mode="json")),
            "first_seen_at": now,
            "last_seen_at": now,
            "last_run_id": run_id,
        }
        conn.execute(
            """
            INSERT INTO deduped_jobs (
                job_key,
                source,
                source_job_id,
                title,
                company,
                location,
                canonical_url,
                content_signature,
                job_json,
                first_seen_at,
                last_seen_at,
                last_run_id
            )
            VALUES (
                :job_key,
                :source,
                :source_job_id,
                :title,
                :company,
                :location,
                :canonical_url,
                :content_signature,
                :job_json,
                :first_seen_at,
                :last_seen_at,
                :last_run_id
            )
            ON CONFLICT(job_key) DO UPDATE SET
                source = excluded.source,
                source_job_id = excluded.source_job_id,
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                canonical_url = excluded.canonical_url,
                content_signature = excluded.content_signature,
                job_json = excluded.job_json,
                last_seen_at = excluded.last_seen_at,
                seen_count = deduped_jobs.seen_count + 1,
                last_run_id = excluded.last_run_id
            """,
            params,
        )

        for identity_type, identity_value in identities:
            self._upsert_job_identity(
                conn=conn,
                identity_type=identity_type,
                identity_value=identity_value,
                job_key=job_key,
                now=now,
            )
        return job_key

    def _upsert_job_identity(
        self,
        *,
        conn: sqlite3.Connection,
        identity_type: str,
        identity_value: str,
        job_key: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO job_identities (
                identity_type,
                identity_value,
                job_key,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(identity_type, identity_value) DO UPDATE SET
                job_key = excluded.job_key,
                last_seen_at = excluded.last_seen_at,
                seen_count = job_identities.seen_count + 1
            """,
            (identity_type, identity_value, job_key, now, now),
        )

    def _upsert_classification_result(
        self,
        *,
        conn: sqlite3.Connection,
        job: JobPosting,
        job_key: str,
        run_id: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO classification_results (
                job_key,
                classifier_version,
                role_tags_json,
                concentration_tags_json,
                classified_job_json,
                first_classified_at,
                last_classified_at,
                last_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_key, classifier_version) DO UPDATE SET
                role_tags_json = excluded.role_tags_json,
                concentration_tags_json = excluded.concentration_tags_json,
                classified_job_json = excluded.classified_job_json,
                last_classified_at = excluded.last_classified_at,
                times_classified = classification_results.times_classified + 1,
                last_run_id = excluded.last_run_id
            """,
            (
                job_key,
                CLASSIFIER_VERSION,
                _json_dumps(job.role_tags),
                _json_dumps(job.concentration_tags),
                _json_dumps(job.model_dump(mode="json")),
                now,
                now,
                run_id,
            ),
        )

    def _upsert_ranking_score(
        self,
        *,
        conn: sqlite3.Connection,
        profile: StudentProfile,
        profile_key: str,
        match: JobMatch,
        job_key: str,
        rank_position: int,
        run_id: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ranking_scores (
                student_key,
                profile_version,
                job_key,
                ranker_version,
                score,
                rank_position,
                reasons_json,
                metadata_json,
                profile_json,
                first_scored_at,
                last_scored_at,
                last_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                student_key,
                profile_version,
                job_key,
                ranker_version
            ) DO UPDATE SET
                score = excluded.score,
                rank_position = excluded.rank_position,
                reasons_json = excluded.reasons_json,
                metadata_json = excluded.metadata_json,
                profile_json = excluded.profile_json,
                last_scored_at = excluded.last_scored_at,
                times_scored = ranking_scores.times_scored + 1,
                last_run_id = excluded.last_run_id
            """,
            (
                profile_key,
                profile.profile_version,
                job_key,
                RANKER_VERSION,
                match.score,
                rank_position,
                _json_dumps(match.reasons),
                _json_dumps(match.metadata),
                _json_dumps(profile.model_dump(mode="json")),
                now,
                now,
                run_id,
            ),
        )

    def _upsert_match_history(
        self,
        *,
        conn: sqlite3.Connection,
        profile: StudentProfile,
        profile_key: str,
        match: JobMatch,
        job_key: str,
        run_id: str,
        now: str,
    ) -> None:
        match_key = _match_key(
            profile_key=profile_key,
            profile_version=profile.profile_version,
            job_key=job_key,
        )
        conn.execute(
            """
            INSERT INTO match_history (
                match_key,
                student_key,
                profile_version,
                job_key,
                ranker_version,
                first_run_id,
                last_run_id,
                first_matched_at,
                last_matched_at,
                latest_score,
                reasons_json,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                student_key,
                profile_version,
                job_key,
                ranker_version
            ) DO UPDATE SET
                last_run_id = excluded.last_run_id,
                last_matched_at = excluded.last_matched_at,
                latest_score = excluded.latest_score,
                reasons_json = excluded.reasons_json,
                metadata_json = excluded.metadata_json,
                times_matched = match_history.times_matched + 1
            """,
            (
                match_key,
                profile_key,
                profile.profile_version,
                job_key,
                RANKER_VERSION,
                run_id,
                run_id,
                now,
                now,
                match.score,
                _json_dumps(match.reasons),
                _json_dumps(match.metadata),
            ),
        )

    def _resolve_job_key(self, conn: sqlite3.Connection, job: JobPosting) -> str | None:
        return self._resolve_job_key_from_identities(conn, _job_identities(job))

    def _resolve_job_key_from_identities(
        self,
        conn: sqlite3.Connection,
        identities: Sequence[tuple[str, str]],
    ) -> str | None:
        for identity_type, identity_value in identities:
            row = conn.execute(
                """
                SELECT job_key
                FROM job_identities
                WHERE identity_type = ? AND identity_value = ?
                """,
                (identity_type, identity_value),
            ).fetchone()
            if row is not None:
                return str(row["job_key"])
        return None


def _job_identities(job: JobPosting) -> list[tuple[str, str]]:
    identities: list[tuple[str, str]] = []
    source_identity = source_job_identity(job)
    if source_identity is not None:
        identities.append(("source_job_id", source_identity))
    canonical_url = canonical_job_url(job)
    if canonical_url is not None:
        identities.append(("canonical_url", canonical_url))
    identities.append(("content_signature", content_signature(job)))
    return list(dict.fromkeys(identities))


def _normalized_job_key(job: JobPosting) -> str:
    identity_type, identity_value = _job_identities(job)[0]
    return stable_hash(f"normalized:{identity_type}:{identity_value}")


def _new_job_key(identities: Sequence[tuple[str, str]]) -> str:
    identity_type, identity_value = identities[0]
    return stable_hash(f"job:{identity_type}:{identity_value}")


def _match_key(
    *,
    profile_key: str,
    profile_version: int,
    job_key: str,
) -> str:
    return stable_hash(
        f"match:{profile_key}:{profile_version}:{job_key}:{RANKER_VERSION}"
    )


def _source_job_id(job: JobPosting) -> str | None:
    raw_metadata = getattr(job, "raw_metadata", {}) or {}
    value = getattr(job, "source_job_id", None) or raw_metadata.get("source_job_id")
    if value is None:
        return None
    normalized_value = str(value).strip()
    return normalized_value or None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _optional_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return str(path)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _summary_int(summary: Mapping[str, Any], key: str, default: int) -> int:
    value = summary.get(key, default)
    if value is None:
        return default
    return int(value)

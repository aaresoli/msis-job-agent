"""PostgreSQL persistence implementing the JobStore protocol."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from hope_job_agent.classification.taxonomy import normalize_concentration
from hope_job_agent.config.database import mask_database_url, resolve_database_url
from hope_job_agent.db.models import JobMatchRecord, StudentProfileRecord
from hope_job_agent.db.session import create_db_engine, create_session_factory
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.persistence.job_repository import JobPostingRepository
from hope_job_agent.persistence.source_run_repository import SourceRunRepository
from hope_job_agent.storage.base import JobStoreError
from hope_job_agent.storage.sqlite_store import student_key

LOGGER = logging.getLogger(__name__)


class PostgresJobStoreError(JobStoreError):
    """Raised when PostgreSQL persistence cannot be configured or completed."""


class PostgresJobStore:
    """PostgreSQL-backed store using repository abstractions."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        storage: str = "postgres",
    ) -> None:
        self.database_url = resolve_database_url(database_url, storage=storage)
        self._engine = create_db_engine(self.database_url, storage="postgres")
        self._session_factory: sessionmaker[Session] = create_session_factory(
            self._engine
        )

    def close(self) -> None:
        self._engine.dispose()

    def preflight(self) -> None:
        try:
            with self._engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - surface connection errors
            safe_url = mask_database_url(self.database_url)
            raise PostgresJobStoreError(
                f"PostgreSQL persistence failed for {safe_url}: {exc}"
            ) from exc

    def table_counts(self, *table_names: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._session_factory() as session:
            for table_name in table_names:
                if not table_name.replace("_", "").isalnum():
                    raise PostgresJobStoreError(f"Unsafe table name: {table_name}")
                count = session.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")  # noqa: S608
                ).scalar_one()
                counts[table_name] = int(count)
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
        metadata = {
            "run_type": run_type,
            "input_path": None if input_path is None else str(input_path),
            "profiles_path": None if profiles_path is None else str(profiles_path),
            "output_path": None if output_path is None else str(output_path),
            "full_refresh": bool(summary.get("full_refresh", False)),
            "summary": dict(summary),
        }
        try:
            with self._session_factory() as session:
                runs = SourceRunRepository(session)
                jobs = JobPostingRepository(session)
                run = runs.start_run(source, run_id=run_id, metadata=metadata)
                upsert_summary = jobs.upsert_many(
                    deduped_jobs,
                    source_run_id=run.id,
                )
                self._persist_matches(session, ranked_matches, job_repo=jobs)
                if metadata["full_refresh"]:
                    seen_ids = [
                        str(job.source_job_id)
                        for job in deduped_jobs
                        if job.source_job_id
                    ]
                    seen_urls = [
                        url
                        for job in deduped_jobs
                        if (url := _canonical_url(job)) is not None
                    ]
                    jobs.mark_missing_jobs_inactive(
                        source,
                        seen_external_ids=seen_ids,
                        seen_urls=seen_urls,
                    )
                finish_summary = {
                    **dict(summary),
                    "jobs_inserted": upsert_summary.inserted,
                    "jobs_updated": upsert_summary.updated,
                    "jobs_skipped": upsert_summary.skipped,
                    "errors": upsert_summary.errors,
                }
                runs.finish_run(run.id, summary=finish_summary)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            raise PostgresJobStoreError(
                f"PostgreSQL persistence failed: {exc}"
            ) from exc

    def _persist_matches(
        self,
        session: Session,
        ranked_matches: Sequence[tuple[StudentProfile, Sequence[JobMatch]]],
        *,
        job_repo: JobPostingRepository,
    ) -> None:
        for profile, matches in ranked_matches:
            student = self._upsert_student(session, profile)
            for match in matches:
                job_record = job_repo.find_duplicate(match.job)
                if job_record is None:
                    job_record = job_repo.upsert_job(match.job)
                session.add(
                    JobMatchRecord(
                        student_id=student.id,
                        job_id=job_record.id,
                        match_score=match.score,
                        rule_score=match.score,
                        explanation="; ".join(match.reasons),
                        matched_at=datetime.now(UTC),
                        metadata_json=match.metadata,
                    )
                )

    def _upsert_student(
        self,
        session: Session,
        profile: StudentProfile,
    ) -> StudentProfileRecord:
        external_id = student_key(profile)
        existing = session.scalar(
            select(StudentProfileRecord).where(
                StudentProfileRecord.external_student_id == external_id
            )
        )
        concentration = normalize_concentration(profile.concentration)
        payload = {
            "external_student_id": external_id,
            "name": profile.name,
            "email": None,
            "concentration": concentration,
            "stage": profile.academic_stage or profile.stage,
            "interests": profile.target_roles or None,
            "skills": profile.skills or None,
            "profile_json": profile.model_dump(mode="json"),
        }
        if existing is None:
            student = StudentProfileRecord(**payload)
            session.add(student)
            session.flush()
            return student
        for key, value in payload.items():
            setattr(existing, key, value)
        session.flush()
        return existing


def _canonical_url(job: JobPosting) -> str | None:
    from hope_job_agent.persistence.dedup import canonicalize_job_url

    return canonicalize_job_url(job)

"""Job posting persistence repository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from hope_job_agent.classification.taxonomy import normalize_concentrations
from hope_job_agent.db.models import JobPostingRecord
from hope_job_agent.models.job import JobPosting
from hope_job_agent.persistence.company_repository import CompanyRepository
from hope_job_agent.persistence.dedup import (
    canonicalize_job_url,
    compute_canonical_fingerprint,
    compute_content_hash,
    normalize_company_name,
    normalize_location,
    normalize_title,
    source_external_identity,
)


@dataclass
class UpsertSummary:
    """Batch upsert counters."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class JobPostingRepository:
    """PostgreSQL repository for normalized job postings."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._companies = CompanyRepository(session)

    def upsert_job(
        self,
        job: JobPosting,
        *,
        source_run_id: uuid.UUID | str | None = None,
    ) -> JobPostingRecord:
        """Insert or update one job posting."""

        summary = UpsertSummary()
        record = self._upsert_one(job, source_run_id=source_run_id, summary=summary)
        if record is None:
            raise RuntimeError("Job upsert failed unexpectedly")
        return record

    def upsert_many(
        self,
        jobs: Sequence[JobPosting],
        *,
        source_run_id: uuid.UUID | str | None = None,
    ) -> UpsertSummary:
        """Upsert many jobs in one transaction batch."""

        summary = UpsertSummary()
        for job in jobs:
            try:
                self._upsert_one(job, source_run_id=source_run_id, summary=summary)
            except Exception as exc:  # noqa: BLE001 - collect per-row import errors
                summary.errors.append(str(exc))
                summary.skipped += 1
        return summary

    def get_by_id(self, job_id: uuid.UUID | str) -> JobPostingRecord | None:
        return self._session.get(JobPostingRecord, _coerce_uuid(job_id))

    def get_by_external_id(
        self,
        source: str,
        external_job_id: str,
    ) -> JobPostingRecord | None:
        return self._session.scalar(
            select(JobPostingRecord).where(
                JobPostingRecord.source == source,
                JobPostingRecord.external_job_id == external_job_id,
            )
        )

    def get_by_canonical_url(self, canonical_url: str) -> JobPostingRecord | None:
        return self._session.scalar(
            select(JobPostingRecord).where(
                JobPostingRecord.canonical_url == canonical_url
            )
        )

    def find_duplicate(self, job: JobPosting) -> JobPostingRecord | None:
        """Find an existing row using deduplication priority."""

        external = source_external_identity(job)
        if external is not None:
            existing = self.get_by_external_id(external[0], external[1])
            if existing is not None:
                return existing

        canonical = canonicalize_job_url(job)
        if canonical is not None:
            existing = self.get_by_canonical_url(canonical)
            if existing is not None:
                return existing

        fingerprint = compute_canonical_fingerprint(job)
        existing = self._session.scalar(
            select(JobPostingRecord).where(
                JobPostingRecord.canonical_fingerprint == fingerprint
            )
        )
        if existing is not None:
            return existing

        content_hash = compute_content_hash(job)
        return self._session.scalar(
            select(JobPostingRecord).where(
                JobPostingRecord.normalized_company_name
                == normalize_company_name(job.company),
                JobPostingRecord.normalized_title == normalize_title(job.title),
                JobPostingRecord.normalized_location
                == normalize_location(job.location),
                JobPostingRecord.content_hash == content_hash,
            )
        )

    def list_recent(
        self,
        *,
        limit: int = 50,
        source: str | None = None,
    ) -> list[JobPostingRecord]:
        stmt = (
            select(JobPostingRecord)
            .order_by(JobPostingRecord.last_seen_at.desc())
            .limit(limit)
        )
        if source:
            stmt = stmt.where(JobPostingRecord.source == source)
        return list(self._session.scalars(stmt))

    def mark_missing_jobs_inactive(
        self,
        source: str,
        seen_external_ids: Sequence[str] | None = None,
        seen_urls: Sequence[str] | None = None,
    ) -> int:
        """Mark jobs inactive when absent from a full refresh run."""

        seen_ids = {str(value).strip() for value in seen_external_ids or [] if value}
        seen_url_set = {str(value).strip() for value in seen_urls or [] if value}
        rows = list(
            self._session.scalars(
                select(JobPostingRecord).where(
                    JobPostingRecord.source == source,
                    JobPostingRecord.status == "active",
                )
            )
        )
        updated = 0
        for row in rows:
            if row.external_job_id and row.external_job_id in seen_ids:
                continue
            if row.canonical_url and row.canonical_url in seen_url_set:
                continue
            row.status = "inactive"
            row.updated_at = datetime.now(UTC)
            updated += 1
        return updated

    def search_jobs(self, filters: Mapping[str, Any]) -> list[JobPostingRecord]:
        stmt: Select[tuple[JobPostingRecord]] = select(JobPostingRecord)
        if source := filters.get("source"):
            stmt = stmt.where(JobPostingRecord.source == source)
        if status := filters.get("status"):
            stmt = stmt.where(JobPostingRecord.status == status)
        if company := filters.get("company"):
            stmt = stmt.where(
                JobPostingRecord.normalized_company_name
                == normalize_company_name(str(company))
            )
        if location := filters.get("location"):
            stmt = stmt.where(
                JobPostingRecord.normalized_location
                == normalize_location(str(location))
            )
        if min_score := filters.get("min_msis_relevance_score"):
            stmt = stmt.where(JobPostingRecord.msis_relevance_score >= float(min_score))
        limit = int(filters.get("limit", 100))
        stmt = stmt.order_by(JobPostingRecord.posted_at.desc().nullslast()).limit(limit)
        return list(self._session.scalars(stmt))

    def get_jobs_needing_embedding(self, *, limit: int = 100) -> list[JobPostingRecord]:
        from hope_job_agent.db.models import JobEmbedding

        stmt = (
            select(JobPostingRecord)
            .outerjoin(JobEmbedding, JobEmbedding.job_id == JobPostingRecord.id)
            .where(JobEmbedding.id.is_(None))
            .order_by(JobPostingRecord.created_at.asc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def get_jobs_needing_classification(
        self,
        *,
        limit: int = 100,
    ) -> list[JobPostingRecord]:
        stmt = (
            select(JobPostingRecord)
            .where(JobPostingRecord.concentration_tags.is_(None))
            .order_by(JobPostingRecord.created_at.asc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def _upsert_one(
        self,
        job: JobPosting,
        *,
        source_run_id: uuid.UUID | str | None,
        summary: UpsertSummary,
    ) -> JobPostingRecord | None:
        now = datetime.now(UTC)
        existing = self.find_duplicate(job)
        company = self._companies.get_or_create_company(job.company)
        payload = _job_to_record_fields(job, company.id, source_run_id, now)

        if existing is None:
            record = JobPostingRecord(**payload)
            self._session.add(record)
            self._session.flush()
            summary.inserted += 1
            return record

        changed = False
        for key, value in payload.items():
            if key in {"first_seen_at", "created_at"}:
                continue
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True
        existing.last_seen_at = now
        existing.updated_at = now
        if changed:
            summary.updated += 1
        else:
            summary.skipped += 1
        return existing


def _job_to_record_fields(
    job: JobPosting,
    company_id: uuid.UUID,
    source_run_id: uuid.UUID | str | None,
    now: datetime,
) -> dict[str, Any]:
    external = source_external_identity(job)
    canonical = canonicalize_job_url(job)
    concentration_tags = normalize_concentrations(job.concentration_tags)
    fetched_at = job.retrieved_at or now
    return {
        "external_job_id": external[1] if external else job.source_job_id,
        "source": job.source,
        "source_detail": job.source_detail,
        "source_run_id": _coerce_uuid(source_run_id),
        "company_id": company_id,
        "company_name": job.company,
        "normalized_company_name": normalize_company_name(job.company),
        "title": job.title,
        "normalized_title": normalize_title(job.title),
        "description": job.description,
        "description_hash": compute_content_hash(job),
        "location": job.location,
        "normalized_location": normalize_location(job.location),
        "remote_status": _map_remote_status(job.location_type),
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "posted_at": job.posted_date,
        "application_deadline": job.application_deadline,
        "source_url": job.url,
        "apply_url": job.apply_url or job.url,
        "department": job.department,
        "team": None,
        "compensation": job.compensation,
        "required_qualifications": None,
        "preferred_qualifications": None,
        "concentration_tags": concentration_tags,
        "msis_relevance_score": job.relevance_score,
        "matched_keywords": job.matched_keywords or None,
        "opt_cpt_flag": job.opt_cpt_flag,
        "opt_cpt_notes": None,
        "status": "active",
        "first_seen_at": now,
        "last_seen_at": now,
        "fetched_at": fetched_at,
        "raw_metadata": job.raw_metadata or None,
        "canonical_url": canonical,
        "canonical_fingerprint": compute_canonical_fingerprint(job),
        "content_hash": compute_content_hash(job),
    }


def _map_remote_status(location_type: str | None) -> str | None:
    if not location_type:
        return None
    normalized = location_type.strip().casefold()
    mapping = {
        "remote": "remote",
        "hybrid": "hybrid",
        "on-site": "onsite",
        "onsite": "onsite",
        "in-person": "onsite",
    }
    return mapping.get(normalized, "unknown")


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))

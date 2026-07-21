"""Aggregate-first GCS reporting and explicitly granted advising access."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import get_db, require_gcs
from hope_job_agent.db.models import JobPostingRecord, SourceRun, StudentProfileRecord
from hope_job_agent.db.platform_models import (
    ApplicationRecord,
    JobEnrichment,
    SharingGrant,
    User,
)
from hope_job_agent.platform.audit import record_audit
from hope_job_agent.platform.settings import PlatformSettings, get_platform_settings

router = APIRouter(prefix="/gcs", tags=["gcs"])


def _suppressed(count: int, minimum: int) -> int | None:
    return count if count >= minimum else None


@router.get("/analytics")
def aggregate_analytics(
    advisor: User = Depends(require_gcs),
    db: Session = Depends(get_db),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    minimum = settings.aggregate_minimum_count
    student_count = (
        db.scalar(select(func.count()).select_from(StudentProfileRecord)) or 0
    )
    active_jobs = (
        db.scalar(
            select(func.count())
            .select_from(JobPostingRecord)
            .where(JobPostingRecord.status == "active")
        )
        or 0
    )
    rows = db.execute(
        select(ApplicationRecord.status, func.count(ApplicationRecord.id)).group_by(
            ApplicationRecord.status
        )
    ).all()
    concentration_rows = db.execute(
        select(StudentProfileRecord.concentration, func.count(StudentProfileRecord.id))
        .where(StudentProfileRecord.concentration.is_not(None))
        .group_by(StudentProfileRecord.concentration)
    ).all()
    record_audit(
        db,
        actor_user_id=advisor.id,
        action="advisor.analytics_viewed",
        resource_type="aggregate_analytics",
    )
    return {
        "student_count": _suppressed(student_count, minimum),
        "active_jobs": active_jobs,
        "minimum_group_size": minimum,
        "application_funnel": {
            status: _suppressed(count, minimum) for status, count in rows
        },
        "concentrations": [
            {"name": name, "count": _suppressed(count, minimum)}
            for name, count in concentration_rows
        ],
    }


@router.get("/sources")
def source_health(
    limit: int = Query(default=50, ge=1, le=200),
    advisor: User = Depends(require_gcs),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    runs = db.scalars(
        select(SourceRun).order_by(SourceRun.started_at.desc()).limit(limit)
    ).all()
    record_audit(
        db,
        actor_user_id=advisor.id,
        action="advisor.source_health_viewed",
        resource_type="source_runs",
    )
    return [
        {
            "id": str(run.id),
            "source": run.source_name,
            "status": run.run_status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "jobs_fetched": run.jobs_fetched,
            "jobs_inserted": run.jobs_inserted,
            "jobs_updated": run.jobs_updated,
            "errors": run.errors_count,
        }
        for run in runs
    ]


@router.get("/review-queue")
def review_queue(
    advisor: User = Depends(require_gcs), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(JobEnrichment, JobPostingRecord)
        .join(JobPostingRecord, JobPostingRecord.id == JobEnrichment.job_id)
        .where((JobEnrichment.status == "review") | (JobEnrichment.confidence < 0.6))
        .order_by(JobEnrichment.created_at.desc())
        .limit(100)
    ).all()
    record_audit(
        db,
        actor_user_id=advisor.id,
        action="advisor.review_queue_viewed",
        resource_type="job_enrichments",
    )
    return [
        {
            "enrichment_id": str(enrichment.id),
            "job_id": str(job.id),
            "title": job.title,
            "company": job.company_name,
            "confidence": enrichment.confidence,
            "status": enrichment.status,
        }
        for enrichment, job in rows
    ]


@router.get("/students/{student_user_id}")
def granted_student_view(
    student_user_id: UUID,
    advisor: User = Depends(require_gcs),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    grant = db.scalar(
        select(SharingGrant).where(
            SharingGrant.student_user_id == student_user_id,
            SharingGrant.advisor_user_id == advisor.id,
            SharingGrant.expires_at > now,
            SharingGrant.revoked_at.is_(None),
        )
    )
    if grant is None:
        raise HTTPException(status_code=404)
    profile = db.scalar(
        select(StudentProfileRecord).where(
            StudentProfileRecord.user_id == student_user_id
        )
    )
    applications = []
    if "applications" in grant.scope:
        rows = db.scalars(
            select(ApplicationRecord).where(
                ApplicationRecord.user_id == student_user_id
            )
        ).all()
        applications = [
            {"company": row.company_name, "role": row.role_title, "status": row.status}
            for row in rows
        ]
    record_audit(
        db,
        actor_user_id=advisor.id,
        subject_user_id=student_user_id,
        action="advisor.student_viewed",
        resource_type="sharing_grant",
        resource_id=str(grant.id),
    )
    return {
        "scope": grant.scope,
        "profile": (
            profile.profile_json if profile and "profile" in grant.scope else None
        ),
        "applications": applications,
    }

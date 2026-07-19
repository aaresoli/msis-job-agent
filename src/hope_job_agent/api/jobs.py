"""Job discovery, personalized match, and feedback routes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import current_user, get_db, require_csrf
from hope_job_agent.api.schemas import JobFeedbackCreate
from hope_job_agent.db.models import (
    JobMatchRecord,
    JobPostingRecord,
    StudentProfileRecord,
)
from hope_job_agent.db.platform_models import (
    JobEnrichment,
    MatchFeedback,
    SavedJob,
    User,
)
from hope_job_agent.platform.audit import record_audit

router = APIRouter(tags=["discovery"])


def _job_payload(
    job: JobPostingRecord, enrichment: JobEnrichment | None = None
) -> dict:
    return {
        "id": str(job.id),
        "title": job.title,
        "company": job.company_name,
        "location": job.location,
        "remote_status": job.remote_status,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "posted_at": job.posted_at,
        "application_deadline": job.application_deadline,
        "description": job.description,
        "source": job.source,
        "source_detail": job.source_detail,
        "source_url": job.source_url,
        "apply_url": job.apply_url or job.source_url,
        "concentration_tags": job.concentration_tags or [],
        "opt_cpt_flag": job.opt_cpt_flag,
        "opt_cpt_notes": job.opt_cpt_notes,
        "status": job.status,
        "skills": enrichment.skills if enrichment else [],
        "requirements": enrichment.requirements if enrichment else [],
        "work_auth_evidence": enrichment.work_auth_evidence if enrichment else [],
        "enrichment_confidence": enrichment.confidence if enrichment else None,
    }


@router.get("/jobs")
def search_jobs(
    q: str | None = Query(default=None, max_length=200),
    location: str | None = Query(default=None, max_length=200),
    concentration: str | None = Query(default=None, max_length=256),
    source: str | None = Query(default=None, max_length=128),
    seniority: str | None = Query(default=None, max_length=64),
    sponsorship_signal: Literal["positive", "restriction", "unknown"] | None = None,
    remote: bool | None = None,
    fresh_days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    del user
    statement = select(JobPostingRecord).where(JobPostingRecord.status == "active")
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            or_(
                JobPostingRecord.title.ilike(pattern),
                JobPostingRecord.company_name.ilike(pattern),
                JobPostingRecord.description.ilike(pattern),
            )
        )
    if location:
        statement = statement.where(JobPostingRecord.location.ilike(f"%{location}%"))
    if concentration:
        statement = statement.where(
            JobPostingRecord.concentration_tags.contains([concentration])
        )
    if source:
        statement = statement.where(JobPostingRecord.source == source)
    if seniority:
        statement = statement.where(JobPostingRecord.seniority.ilike(seniority))
    if sponsorship_signal == "positive":
        statement = statement.where(JobPostingRecord.opt_cpt_flag.is_(True))
    elif sponsorship_signal == "restriction":
        statement = statement.where(JobPostingRecord.opt_cpt_flag.is_(False))
    elif sponsorship_signal == "unknown":
        statement = statement.where(JobPostingRecord.opt_cpt_flag.is_(None))
    if remote is True:
        statement = statement.where(
            JobPostingRecord.remote_status.in_(["remote", "hybrid"])
        )
    if fresh_days:
        statement = statement.where(
            JobPostingRecord.posted_at >= date.today() - timedelta(days=fresh_days)
        )
    statement = statement.order_by(
        JobPostingRecord.posted_at.desc().nullslast(), JobPostingRecord.title
    )
    jobs = db.scalars(statement.offset(offset).limit(limit)).all()
    return {
        "items": [_job_payload(job) for job in jobs],
        "limit": limit,
        "offset": offset,
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    del user
    job = db.get(JobPostingRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    enrichment = db.scalar(
        select(JobEnrichment)
        .where(JobEnrichment.job_id == job.id)
        .order_by(JobEnrichment.created_at.desc())
        .limit(1)
    )
    return _job_payload(job, enrichment)


@router.get("/matches")
def list_matches(
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.scalar(
        select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
    )
    if profile is None:
        return {"items": [], "needs_profile": True}
    rows = db.execute(
        select(JobMatchRecord, JobPostingRecord)
        .join(JobPostingRecord, JobPostingRecord.id == JobMatchRecord.job_id)
        .where(JobMatchRecord.student_id == profile.id)
        .order_by(JobMatchRecord.match_score.desc())
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "match_id": str(match.id),
                "score": match.match_score,
                "rule_score": match.rule_score,
                "vector_score": match.vector_score,
                "llm_score": match.llm_score,
                "confidence": match.confidence,
                "status": match.status,
                "explanation": match.explanation,
                "ranking_version": match.ranking_version,
                "job": _job_payload(job),
            }
            for match, job in rows
        ],
        "needs_profile": False,
    }


@router.post("/jobs/{job_id}/feedback")
def record_feedback(
    job_id: UUID,
    payload: JobFeedbackCreate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(JobPostingRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    feedback = db.scalar(
        select(MatchFeedback).where(
            MatchFeedback.user_id == user.id, MatchFeedback.job_id == job_id
        )
    )
    if feedback is None:
        feedback = MatchFeedback(user_id=user.id, job_id=job_id, action=payload.action)
        db.add(feedback)
    feedback.action = payload.action
    feedback.reason = payload.reason
    if payload.action == "saved":
        saved = db.scalar(
            select(SavedJob).where(
                SavedJob.user_id == user.id, SavedJob.job_id == job_id
            )
        )
        if saved is None:
            db.add(SavedJob(user_id=user.id, job_id=job_id))
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action=f"match.{payload.action}",
        resource_type="job",
        resource_id=str(job_id),
    )
    return {"job_id": str(job_id), "action": payload.action}

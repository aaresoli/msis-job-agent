"""Private n8n and service-to-service endpoints."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import get_db, require_internal_service
from hope_job_agent.api.schemas import ApifyWebhook, BatchRequest, SourceRunRequest
from hope_job_agent.db.models import (
    JobMatchRecord,
    JobPostingRecord,
    SourceRun,
    StudentProfileRecord,
)
from hope_job_agent.db.platform_models import (
    ApplicationRecord,
    IdempotencyRecord,
    JobEnrichment,
    MarketPost,
    Notification,
    OutboxEvent,
    SourceQuarantineRecord,
    SourceWebhookReceipt,
    User,
)
from hope_job_agent.persistence.job_repository import JobPostingRepository
from hope_job_agent.platform.settings import PlatformSettings, get_platform_settings
from hope_job_agent.sources.apify import normalize_apify_job, normalize_apify_post
from hope_job_agent.workers.tasks import (
    enforce_retention,
    enrich_job,
    generate_profile_matches,
    refresh_market_pulse,
)

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.post("/users/invite", dependencies=[Depends(require_internal_service)])
def invite_user(
    email: str,
    role: str = "student",
    db: Session = Depends(get_db),
) -> dict:
    normalized = email.strip().casefold()
    if role not in {"student", "gcs", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        user = User(email=normalized, role=role)
        db.add(user)
        db.flush()
    return {"id": str(user.id), "email": user.email, "status": user.status}


@router.post(
    "/sources/{source_name}/execute", dependencies=[Depends(require_internal_service)]
)
def execute_source(source_name: str, payload: SourceRunRequest) -> dict:
    if source_name in {"ksbit_denodo", "apify_linkedin"}:
        return {
            "source": source_name,
            "status": "disabled",
            "reason": "Endpoint mapping and source approval are required",
        }
    return {
        "source": source_name,
        "status": "accepted",
        "request": payload.model_dump(mode="json"),
    }


@router.post("/batches/enrich", dependencies=[Depends(require_internal_service)])
def enqueue_enrichment(payload: BatchRequest) -> dict:
    task_ids = [enrich_job.delay(str(item)).id for item in payload.ids]
    return {"status": "accepted", "task_ids": task_ids}


@router.post("/batches/match", dependencies=[Depends(require_internal_service)])
def enqueue_matching(payload: BatchRequest) -> dict:
    task_ids = [generate_profile_matches.delay(str(item)).id for item in payload.ids]
    return {"status": "accepted", "task_ids": task_ids}


@router.post("/reconciliation", dependencies=[Depends(require_internal_service)])
def reconcile_missing_work(db: Session = Depends(get_db)) -> dict:
    job_ids = db.scalars(
        select(JobPostingRecord.id)
        .outerjoin(
            JobEnrichment,
            (JobEnrichment.job_id == JobPostingRecord.id)
            & (JobEnrichment.version == "enrichment-v1"),
        )
        .where(JobPostingRecord.status == "active", JobEnrichment.id.is_(None))
        .limit(1000)
    ).all()
    profile_ids = db.scalars(select(StudentProfileRecord.id).limit(1000)).all()
    enrichment_tasks = [enrich_job.delay(str(item)).id for item in job_ids]
    match_tasks = [generate_profile_matches.delay(str(item)).id for item in profile_ids]
    return {
        "status": "accepted",
        "enrichment_tasks": enrichment_tasks,
        "match_tasks": match_tasks,
    }


@router.post("/digests/{cadence}", dependencies=[Depends(require_internal_service)])
def request_digests(cadence: str, db: Session = Depends(get_db)) -> dict:
    if cadence not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="Unsupported digest cadence")
    users = db.scalars(
        select(User).where(User.role == "student", User.status == "active")
    ).all()
    created = 0
    for user in users:
        profile = db.scalar(
            select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
        )
        if profile is None:
            continue
        match_count = (
            db.scalar(
                select(func.count(JobMatchRecord.id)).where(
                    JobMatchRecord.student_id == profile.id,
                    JobMatchRecord.status.in_(["ready", "degraded"]),
                )
            )
            or 0
        )
        if not match_count:
            continue
        db.add(
            Notification(
                user_id=user.id,
                kind=f"{cadence}_digest",
                title=f"Your {cadence} HOPE brief is ready",
                body=f"You have {match_count} current career matches to review.",
                action_url="/today",
            )
        )
        db.add(
            OutboxEvent(
                event_type="digest.requested.v1",
                aggregate_type="user",
                aggregate_id=str(user.id),
                payload={"cadence": cadence, "email": user.email},
            )
        )
        created += 1
    return {"status": "accepted", "digests": created, "cadence": cadence}


@router.post(
    "/reminders/applications", dependencies=[Depends(require_internal_service)]
)
def create_application_reminders(db: Session = Depends(get_db)) -> dict:
    today = datetime.now(UTC).date()
    upcoming = db.scalars(
        select(ApplicationRecord).where(
            ApplicationRecord.deadline.is_not(None),
            ApplicationRecord.deadline >= today,
            ApplicationRecord.deadline <= today + timedelta(days=7),
            ApplicationRecord.status.in_(["saved", "preparing"]),
        )
    ).all()
    for application in upcoming:
        db.add(
            Notification(
                user_id=application.user_id,
                kind="application_deadline",
                title=f"Deadline: {application.role_title}",
                body=f"{application.company_name} is due {application.deadline}.",
                action_url="/applications",
            )
        )
    return {"status": "created", "reminders": len(upcoming)}


@router.get("/alerts/source-health", dependencies=[Depends(require_internal_service)])
def source_health_alerts(db: Session = Depends(get_db)) -> dict:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    failures = db.scalars(
        select(SourceRun).where(
            SourceRun.started_at >= cutoff,
            SourceRun.run_status.in_(["failed", "partial"]),
        )
    ).all()
    return {
        "status": "attention" if failures else "healthy",
        "failures": [
            {
                "source": row.source_name,
                "status": row.run_status,
                "errors": row.errors_count,
                "summary": row.error_summary,
            }
            for row in failures
        ],
    }


@router.post("/retention", dependencies=[Depends(require_internal_service)])
def enqueue_retention() -> dict:
    task = enforce_retention.delay()
    return {"status": "accepted", "task_id": task.id}


@router.post("/webhooks/apify", status_code=status.HTTP_202_ACCEPTED)
async def apify_webhook(
    request: Request,
    payload: ApifyWebhook,
    signature: str | None = Header(default=None, alias="X-Apify-Signature"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    if not settings.source_approval_id:
        raise HTTPException(status_code=403, detail="Apify source is not approved")
    secret = settings.apify_webhook_secret.get_secret_value()
    body = await request.body()
    expected = (
        hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if secret else ""
    )
    if not signature or not expected or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    key = idempotency_key or f"apify:{payload.event_id}"
    existing = db.get(IdempotencyRecord, key)
    if existing is not None:
        return existing.response_payload or {"status": "duplicate"}
    receipt = SourceWebhookReceipt(
        source="apify_linkedin",
        external_event_id=payload.event_id,
        payload_hash=hashlib.sha256(body).hexdigest(),
        status="processing",
    )
    db.add(receipt)
    inserted = 0
    quarantined = 0
    if payload.resource_type == "job":
        jobs = []
        for item in payload.items:
            try:
                jobs.append(normalize_apify_job(item, payload.actor_run_id))
            except (ValidationError, ValueError) as exc:
                db.add(
                    SourceQuarantineRecord(
                        source="apify_linkedin_jobs",
                        external_event_id=payload.event_id,
                        reason=str(exc)[:512],
                        payload=item,
                        expires_at=datetime.now(UTC) + timedelta(days=30),
                    )
                )
                quarantined += 1
        summary = JobPostingRepository(db).upsert_many(jobs)
        inserted = summary.inserted + summary.updated
        repository = JobPostingRepository(db)
        for job in jobs:
            if not job.source_job_id:
                continue
            record = repository.get_by_external_id(job.source, job.source_job_id)
            if record is None:
                continue
            db.add(
                OutboxEvent(
                    event_type="job.upserted.v1",
                    aggregate_type="job",
                    aggregate_id=str(record.id),
                    payload={"source": job.source},
                )
            )
            enrich_job.apply_async(args=[str(record.id)], countdown=2)
    else:
        for item in payload.items:
            normalized = normalize_apify_post(item, payload.actor_run_id)
            if not normalized["content"] or not normalized["source_url"]:
                db.add(
                    SourceQuarantineRecord(
                        source="apify_linkedin_posts",
                        external_event_id=payload.event_id,
                        reason="Post requires content and a source URL",
                        payload=item,
                        expires_at=datetime.now(UTC) + timedelta(days=30),
                    )
                )
                quarantined += 1
                continue
            existing_post = db.scalar(
                select(MarketPost).where(
                    MarketPost.source == normalized["source"],
                    MarketPost.external_id == normalized["external_id"],
                )
            )
            if existing_post is not None:
                continue
            published = normalized["published_at"]
            if isinstance(published, str):
                try:
                    published = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    published = None
            normalized["published_at"] = published
            db.add(MarketPost(**normalized))
            inserted += 1
        if inserted:
            refresh_market_pulse.apply_async(countdown=2)
    receipt.status = "processed"
    response = {
        "status": "accepted",
        "processed": inserted,
        "quarantined": quarantined,
        "event_id": payload.event_id,
    }
    db.add(
        IdempotencyRecord(
            key=key,
            scope="apify.webhook",
            request_hash=hashlib.sha256(body).hexdigest(),
            response_code=202,
            response_payload=response,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    return response


@router.post("/backup/verified", dependencies=[Depends(require_internal_service)])
def backup_verified(
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> dict:
    return {
        "status": "recorded",
        "request_id": request_id or str(uuid4()),
        "verified_at": datetime.now(UTC),
    }

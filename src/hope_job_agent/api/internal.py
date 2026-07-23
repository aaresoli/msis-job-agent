"""Private service-to-service endpoints.

These are the operator-facing half of the scheduled work in
:mod:`hope_job_agent.workers.schedules`: same functions, triggered by hand.
They are not the scheduler -- nothing polls them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import get_db, require_internal_service
from hope_job_agent.api.schemas import ApifyWebhook, BatchRequest, SourceRunRequest
from hope_job_agent.db.models import SourceRun
from hope_job_agent.db.platform_models import (
    IdempotencyRecord,
    MarketPost,
    OutboxEvent,
    SourceQuarantineRecord,
    SourceWebhookReceipt,
    User,
)
from hope_job_agent.ops.backup import latest_backup
from hope_job_agent.ops.digests import UnsupportedCadence, queue_digests
from hope_job_agent.ops.reconcile import find_reconciliation_backlog
from hope_job_agent.ops.reminders import create_application_reminders
from hope_job_agent.persistence.job_repository import JobPostingRepository
from hope_job_agent.platform.settings import PlatformSettings, get_platform_settings
from hope_job_agent.sources.apify import normalize_apify_job, normalize_apify_post
from hope_job_agent.sources.apify_linkedin import ApifyLinkedInSettings
from hope_job_agent.sources.registry import (
    SourceComplianceError,
    ensure_source_allowed,
)
from hope_job_agent.workers.ops_tasks import backup_database
from hope_job_agent.workers.tasks import (
    EMBEDDING_BATCH_SIZE,
    REFRESHABLE_SOURCES,
    embed_jobs,
    enforce_retention,
    enrich_job,
    generate_profile_matches,
    refresh_all,
    refresh_market_pulse,
    refresh_source,
)

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.post("/users/invite", dependencies=[Depends(require_internal_service)])
def invite_user(
    email: str,
    role: str = "student",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized = email.strip().casefold()
    if role not in {"student", "gcs", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        user = User(email=normalized, role=role)
        db.add(user)
        db.flush()
    return {"id": str(user.id), "email": user.email, "status": user.status}


@router.post("/sources/refresh-all", dependencies=[Depends(require_internal_service)])
def execute_refresh_all(
    payload: SourceRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Queue one sweep over every scheduled source (jobs, then posts, then signals).

    This is the endpoint schedulers should call; ``/sources/{name}/execute``
    stays available for refreshing a single source by hand.
    """

    # Schedulers retry on timeout; dedupe so one window cannot start two sweeps.
    key = f"source-refresh-all:{request.state.idempotency_key}"
    existing = db.get(IdempotencyRecord, key)
    if existing is not None:
        return existing.response_payload or {"status": "duplicate"}

    task = refresh_all.delay(limit=payload.limit, dry_run=payload.dry_run)
    response = {"status": "accepted", "task_id": task.id}
    db.add(
        IdempotencyRecord(
            key=key,
            scope="sources.refresh_all",
            request_hash=hashlib.sha256(
                json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest(),
            response_code=200,
            response_payload=response,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    return response


@router.post(
    "/sources/{source_name}/execute", dependencies=[Depends(require_internal_service)]
)
def execute_source(
    source_name: str,
    payload: SourceRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if source_name not in REFRESHABLE_SOURCES:
        return {
            "source": source_name,
            "status": "disabled",
            "reason": (
                "Endpoint mapping and source approval are required before this "
                "source can be refreshed on a schedule"
            ),
        }
    try:
        ensure_source_allowed(source_name)
    except SourceComplianceError as exc:
        return {"source": source_name, "status": "disabled", "reason": str(exc)}
    if (
        source_name == "apify_linkedin"
        and not ApifyLinkedInSettings().apify_token.get_secret_value().strip()
    ):
        return {
            "source": source_name,
            "status": "disabled",
            "reason": "APIFY_TOKEN is not configured",
        }

    # Schedulers retry on timeout; dedupe so one window cannot start two crawls.
    key = f"source-execute:{source_name}:{request.state.idempotency_key}"
    existing = db.get(IdempotencyRecord, key)
    if existing is not None:
        return existing.response_payload or {"status": "duplicate"}

    task = refresh_source.delay(
        source_name,
        limit=payload.limit,
        max_companies=payload.max_companies,
        dry_run=payload.dry_run,
    )
    response = {"source": source_name, "status": "accepted", "task_id": task.id}
    db.add(
        IdempotencyRecord(
            key=key,
            scope="sources.execute",
            request_hash=hashlib.sha256(
                json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest(),
            response_code=200,
            response_payload=response,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    return response


@router.post("/batches/enrich", dependencies=[Depends(require_internal_service)])
def enqueue_enrichment(payload: BatchRequest) -> dict[str, Any]:
    job_ids = [str(item) for item in payload.ids]
    task_ids = [enrich_job.delay(item).id for item in job_ids]
    # Embedding is enqueued alongside, not inside, enrichment: a posting whose
    # enrichment is routed to review still needs a vector, because similarity
    # search is what surfaces it at all.
    embedding_tasks = _enqueue_embeddings(job_ids)
    return {
        "status": "accepted",
        "task_ids": task_ids,
        "embedding_tasks": embedding_tasks,
    }


def _enqueue_embeddings(job_ids: list[str]) -> list[str]:
    """Enqueue embedding work in batches the provider can serve in one call."""

    return [
        embed_jobs.delay(job_ids[start : start + EMBEDDING_BATCH_SIZE]).id
        for start in range(0, len(job_ids), EMBEDDING_BATCH_SIZE)
    ]


@router.post("/batches/match", dependencies=[Depends(require_internal_service)])
def enqueue_matching(payload: BatchRequest) -> dict[str, Any]:
    task_ids = [generate_profile_matches.delay(str(item)).id for item in payload.ids]
    return {"status": "accepted", "task_ids": task_ids}


@router.post("/reconciliation", dependencies=[Depends(require_internal_service)])
def reconcile_missing_work(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Manually trigger the reconciliation the scheduler runs nightly."""

    backlog = find_reconciliation_backlog(db)
    return {
        "status": "accepted",
        "enrichment_tasks": [
            enrich_job.delay(item).id for item in backlog["unenriched"]
        ],
        "match_tasks": [
            generate_profile_matches.delay(item).id for item in backlog["profiles"]
        ],
        "embedding_tasks": _enqueue_embeddings(backlog["unembedded"]),
    }


@router.post("/digests/{cadence}", dependencies=[Depends(require_internal_service)])
def request_digests(cadence: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Manually queue a digest cadence the scheduler otherwise runs on its own."""

    try:
        return queue_digests(db, cadence)
    except UnsupportedCadence as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/reminders/applications", dependencies=[Depends(require_internal_service)]
)
def request_application_reminders(db: Session = Depends(get_db)) -> dict[str, Any]:
    return create_application_reminders(db)


@router.get("/alerts/source-health", dependencies=[Depends(require_internal_service)])
def source_health_alerts(db: Session = Depends(get_db)) -> dict[str, Any]:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    failures = db.scalars(
        select(SourceRun).where(
            SourceRun.started_at >= cutoff,
            SourceRun.run_status.in_(["failed", "partial", "partial_success"]),
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
def enqueue_retention() -> dict[str, Any]:
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
) -> dict[str, Any]:
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


@router.post("/backup", dependencies=[Depends(require_internal_service)])
def trigger_backup() -> dict[str, Any]:
    """Run a backup now. The task's single-flight lock rejects an overlap."""

    task = backup_database.delay()
    return {"status": "accepted", "task_id": task.id}


@router.get("/backup/verified", dependencies=[Depends(require_internal_service)])
def backup_verified(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Report the most recent backup, from the record the backup task wrote.

    This used to be a POST that returned ``{"status": "recorded"}`` whatever the
    state of the world -- called nightly by a workflow that was never activated,
    against a system that had never taken a backup. Reading the row means the
    answer can be "none", which is the answer that matters.
    """

    record = latest_backup(db)
    if record is None:
        return {"status": "none", "verified": False}
    return {
        "status": record.status,
        "verified": record.verified,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "object_key": record.object_key,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "verified_tables": record.verified_tables,
        "error_summary": record.error_summary,
    }

"""Celery tasks for scheduled operations.

Thin wrappers: each one opens a session, calls a function in
:mod:`hope_job_agent.ops`, and returns its summary. The logic lives there so the
operator-facing ``/internal/v1`` routes and the scheduler run the same code.

These are routed to their own ``ops`` queue. Maintenance work is long
(a backup restore) or latency-sensitive in a different way (the outbox relay
runs every 30 seconds), and neither should sit behind a GPU-bound enrichment
backlog on the ``batch`` queue.
"""

from __future__ import annotations

import logging
from typing import Any

from hope_job_agent.db.session import session_scope
from hope_job_agent.ops import metrics, reconcile
from hope_job_agent.ops.backup import run_backup
from hope_job_agent.ops.digests import queue_digests
from hope_job_agent.ops.locks import AlreadyRunning, single_flight
from hope_job_agent.ops.outbox import relay_pending
from hope_job_agent.ops.reminders import create_application_reminders
from hope_job_agent.workers.celery_app import celery_app
from hope_job_agent.workers.tasks import (
    embed_jobs,
    enrich_job,
    generate_profile_matches,
    session_factory,
)

LOGGER = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 32
# Comfortably longer than the task's own soft time limit, so the lock is only
# ever released by the run that took it or by a worker dying.
BACKUP_LOCK_TTL_SECONDS = 7200


@celery_app.task(name="hope.ops.relay_outbox")
def relay_outbox() -> dict[str, Any]:
    """Publish pending outbox events. Scheduled frequently; safe to overlap."""

    with session_scope(session_factory()) as db:
        return relay_pending(db)


@celery_app.task(name="hope.ops.send_digests")
def send_digests(cadence: str = "daily") -> dict[str, Any]:
    """Queue one cadence of student digests.

    Only writes rows. The mail itself goes out through the outbox relay, so a
    slow or unavailable SMTP relay cannot leave a run half-delivered.
    """

    with session_scope(session_factory()) as db:
        return queue_digests(db, cadence)


@celery_app.task(name="hope.ops.application_reminders")
def application_reminders() -> dict[str, Any]:
    with session_scope(session_factory()) as db:
        return create_application_reminders(db)


@celery_app.task(name="hope.ops.reconcile")
def reconcile_backlog() -> dict[str, Any]:
    """Re-enqueue enrichment, embedding, and matching that never completed."""

    with session_scope(session_factory()) as db:
        backlog = reconcile.find_reconciliation_backlog(db)
    for job_id in backlog["unenriched"]:
        enrich_job.delay(job_id)
    for profile_id in backlog["profiles"]:
        generate_profile_matches.delay(profile_id)
    unembedded = backlog["unembedded"]
    for start in range(0, len(unembedded), EMBEDDING_BATCH_SIZE):
        embed_jobs.delay(unembedded[start : start + EMBEDDING_BATCH_SIZE])
    return reconcile.summarize(backlog)


@celery_app.task(
    name="hope.ops.backup",
    # A backup takes what it takes; retrying a half-finished dump on a timeout
    # would stack two pg_dumps on the same database.
    time_limit=5400,
    soft_time_limit=5100,
    max_retries=0,
)
def backup_database() -> dict[str, Any]:
    try:
        with single_flight("backup", BACKUP_LOCK_TTL_SECONDS):
            with session_scope(session_factory()) as db:
                return run_backup(db)
    except AlreadyRunning:
        LOGGER.warning("Backup already running; skipping this window")
        return {"status": "skipped", "reason": "already running"}


@celery_app.task(name="hope.ops.export_metrics")
def export_metrics() -> dict[str, Any]:
    """Sample the platform-health gauges the alerting rules fire on."""

    with session_scope(session_factory()) as db:
        return metrics.refresh_gauges(db)


@celery_app.task(name="hope.ops.heartbeat")
def heartbeat() -> dict[str, Any]:
    """Prove the scheduler is dispatching.

    Beat has no health endpoint and no ping. Without this, a dead scheduler
    looks exactly like a quiet night: no crawls, no digests, no alerts.
    """

    metrics.record_heartbeat()
    return {"status": "ok"}

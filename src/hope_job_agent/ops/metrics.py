"""Platform-health gauges, sampled on a schedule.

These are the numbers alerting rules fire on. They are deliberately *derived
from the database and Redis*, not accumulated in process memory: a Celery worker
is a forked, restartable process, so anything held in memory resets to zero and
an alert on it would clear itself by crashing. ``hope_backup_age_seconds`` is
the clearest case -- it is only trustworthy because ``backup_runs`` outlives
every process that writes it.

The counters in :mod:`hope_job_agent.ai.telemetry` are the complement to this
module: those measure work as it happens, these measure standing state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

import httpx
import redis
from prometheus_client import Gauge
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import SourceRun
from hope_job_agent.db.platform_models import BackupRun, OutboxEvent
from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

# Celery queue names, mirroring workers/celery_app.py. Redis stores a queue as
# a list keyed by the queue name, so LLEN is the pending-task count.
QUEUE_NAMES = ("interactive", "batch", "ingest", "ops")

# "livemostrecent": the sampler is a single task writing an absolute value, and
# only the newest sample from a live process is meaningful. The default "all"
# would expose one stale series per dead worker pid.
_MODE: Literal["livemostrecent"] = "livemostrecent"


@dataclass(frozen=True)
class _Gauges:
    source_failures: Gauge
    backup_age: Gauge
    backup_verified: Gauge
    outbox_pending: Gauge
    outbox_oldest_age: Gauge
    outbox_dead_lettered: Gauge
    queue_depth: Gauge
    model_loaded: Gauge
    beat_heartbeat: Gauge


@lru_cache(maxsize=1)
def gauges() -> _Gauges:
    """Build the gauges, once, in the process that actually samples them.

    Deliberately lazy rather than module-level. Every Celery worker imports this
    module through the task registry, and creating a Gauge publishes it
    immediately at 0 -- so module-level definitions had all four workers
    exporting ``hope_backup_last_verified 0`` while only the ops worker exported
    the real value. Prometheus then held four series per gauge, three of them
    fiction, and ``HopeBackupUnverified`` (``== 0``) fired permanently.

    Creating them on first sample means a worker that never samples never
    publishes the series at all.
    """

    return _Gauges(
        source_failures=Gauge(
            "hope_source_run_failures_24h",
            "Source runs that failed or partially failed in the last 24 hours.",
            multiprocess_mode=_MODE,
        ),
        backup_age=Gauge(
            "hope_backup_age_seconds",
            "Seconds since the last successfully verified backup.",
            multiprocess_mode=_MODE,
        ),
        backup_verified=Gauge(
            "hope_backup_last_verified",
            "1 when the most recent backup run restored and verified cleanly.",
            multiprocess_mode=_MODE,
        ),
        outbox_pending=Gauge(
            "hope_outbox_unpublished",
            "Outbox events awaiting relay.",
            multiprocess_mode=_MODE,
        ),
        outbox_oldest_age=Gauge(
            "hope_outbox_oldest_age_seconds",
            "Age of the oldest unpublished outbox event.",
            multiprocess_mode=_MODE,
        ),
        outbox_dead_lettered=Gauge(
            "hope_outbox_dead_lettered",
            "Outbox events that exhausted their relay attempts.",
            multiprocess_mode=_MODE,
        ),
        queue_depth=Gauge(
            "hope_celery_queue_depth",
            "Tasks waiting in each Celery queue.",
            ("queue",),
            multiprocess_mode=_MODE,
        ),
        model_loaded=Gauge(
            "hope_vllm_model_loaded",
            "1 when the chat server lists the labelled model on /v1/models. "
            "A flip to 0 means the engine restarted or the model was unloaded.",
            ("model",),
            multiprocess_mode=_MODE,
        ),
        beat_heartbeat=Gauge(
            "hope_beat_heartbeat_timestamp_seconds",
            "Unix time of the last scheduler heartbeat. Nothing else observes "
            "beat, so this is the only signal that the scheduler is alive.",
            multiprocess_mode=_MODE,
        ),
    )


# Models seen resident at least once, so an eviction can be published as a 0
# rather than silently leaving the last 1 in place.
_SEEN_MODELS: set[str] = set()


def refresh_gauges(db: Session) -> dict[str, Any]:
    """Sample every platform-health gauge and return the values for logging."""

    now = datetime.now(UTC)
    sampled: dict[str, Any] = {}
    sampled["source_failures_24h"] = _sample_source_failures(db, now)
    sampled.update(_sample_backup(db, now))
    sampled.update(_sample_outbox(db, now))
    sampled["queue_depth"] = _sample_queue_depth()
    sampled["models_loaded"] = _sample_loaded_models()
    return sampled


def record_heartbeat() -> None:
    """Record that beat dispatched on schedule."""

    gauges().beat_heartbeat.set(datetime.now(UTC).timestamp())


def _sample_source_failures(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(hours=24)
    count = (
        db.scalar(
            select(func.count(SourceRun.id)).where(
                SourceRun.started_at >= cutoff,
                SourceRun.run_status.in_(["failed", "partial", "partial_success"]),
            )
        )
        or 0
    )
    gauges().source_failures.set(count)
    return int(count)


def _sample_backup(db: Session, now: datetime) -> dict[str, Any]:
    latest = db.scalar(
        select(BackupRun)
        .where(BackupRun.verified.is_(True))
        .order_by(BackupRun.finished_at.desc())
        .limit(1)
    )
    if latest is None or latest.finished_at is None:
        # No verified backup is the worst state, not a missing metric. Reporting
        # "no data" would leave the staleness alert silent on a brand-new or
        # totally broken deployment, which is when it matters most.
        gauges().backup_age.set(float("inf"))
        gauges().backup_verified.set(0)
        return {"backup_age_seconds": None, "backup_verified": False}
    age = (now - latest.finished_at).total_seconds()
    gauges().backup_age.set(age)
    gauges().backup_verified.set(1)
    return {"backup_age_seconds": age, "backup_verified": True}


def _sample_outbox(db: Session, now: datetime) -> dict[str, Any]:
    settings = get_platform_settings()
    pending = (
        db.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.attempts < settings.outbox_max_attempts,
            )
        )
        or 0
    )
    dead = (
        db.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.attempts >= settings.outbox_max_attempts,
            )
        )
        or 0
    )
    oldest = db.scalar(
        select(func.min(OutboxEvent.created_at)).where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.attempts < settings.outbox_max_attempts,
        )
    )
    age = (now - oldest).total_seconds() if oldest is not None else 0.0
    gauges().outbox_pending.set(pending)
    gauges().outbox_dead_lettered.set(dead)
    gauges().outbox_oldest_age.set(age)
    return {
        "outbox_pending": int(pending),
        "outbox_dead_lettered": int(dead),
        "outbox_oldest_age_seconds": age,
    }


def _sample_queue_depth() -> dict[str, int]:
    depths: dict[str, int] = {}
    try:
        client = redis.Redis.from_url(get_platform_settings().redis_url)
        for queue in QUEUE_NAMES:
            depth = int(client.llen(queue))  # type: ignore[arg-type]
            gauges().queue_depth.labels(queue=queue).set(depth)
            depths[queue] = depth
    except redis.RedisError as exc:
        # Redis being unreachable is already alerted on by the broker-level
        # `up` check; failing here would take the other gauges down with it.
        LOGGER.warning("Queue depth sample failed: %s", exc)
    return depths


def _sample_loaded_models() -> list[str]:
    """Report which models the vLLM chat server currently advertises.

    vLLM keeps weights resident for the life of the process, so this is really
    an liveness/identity check: a flip to 0 means the engine restarted or the
    configured model id disappeared from ``/v1/models``.
    """

    base_url = get_platform_settings().vllm_base_url.rstrip("/")
    if not base_url:
        return []
    try:
        response = httpx.get(f"{base_url}/v1/models", timeout=5.0)
        response.raise_for_status()
        models = [
            str(item["id"])
            for item in response.json().get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        LOGGER.warning("vLLM model sample failed: %s", exc)
        return []
    # Previously-seen models must go to 0 rather than keep their last value,
    # otherwise an unload looks identical to a model that is still served.
    for model in _SEEN_MODELS - set(models):
        gauges().model_loaded.labels(model=model).set(0)
    for model in models:
        gauges().model_loaded.labels(model=model).set(1)
        _SEEN_MODELS.add(model)
    return models

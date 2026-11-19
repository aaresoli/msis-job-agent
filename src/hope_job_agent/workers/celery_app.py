"""Celery configuration: queues, routing, and the platform schedule."""

from celery import Celery
from kombu import Queue

from hope_job_agent.platform.settings import get_platform_settings
from hope_job_agent.workers.schedules import BEAT_SCHEDULE

settings = get_platform_settings()
celery_app = Celery(
    "hope_job_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "hope_job_agent.workers.tasks",
        "hope_job_agent.workers.ops_tasks",
    ],
)
celery_app.conf.update(
    task_queues=(
        Queue("interactive", routing_key="interactive"),
        Queue("batch", routing_key="batch"),
        Queue("ingest", routing_key="ingest"),
        # Scheduled maintenance: the outbox relay, digests, backups, metric
        # sampling. Separated from `batch` because those are GPU-bound and a
        # thirty-second relay must not wait behind an enrichment backlog, and
        # from `ingest` because a nightly backup must not wait behind an
        # hour-long ATS crawl.
        Queue("ops", routing_key="ops"),
    ),
    task_routes={
        "hope.coach.*": {"queue": "interactive"},
        "hope.enrichment.*": {"queue": "batch"},
        "hope.matching.*": {"queue": "batch"},
        "hope.privacy.*": {"queue": "ops"},
        "hope.sources.*": {"queue": "ingest"},
        # hope.market.refresh matched no route before this line existed, so it
        # was dispatched to Celery's default "celery" queue -- which no worker
        # consumes. Every Market Pulse refresh triggered by the Apify webhook
        # was enqueued and never executed.
        "hope.market.*": {"queue": "batch"},
        "hope.ops.*": {"queue": "ops"},
    },
    # A task that matches no route above lands somewhere a worker is actually
    # listening, rather than silently accumulating in an unread queue.
    task_default_queue="ops",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Local LLM inference on the Spark is slow on a cold model load; the
    # per-task overrides on source refresh raise this much further.
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=86400,
    beat_schedule=BEAT_SCHEDULE,
    # Schedule entries use local crontabs so an 8 AM digest stays at 8 AM
    # across a DST change.
    timezone="America/Indiana/Indianapolis",
    enable_utc=True,
)

# Importing for the signal side effects: this is what starts the metrics
# endpoint on a worker and clears a dead child's gauge files.
from hope_job_agent.ops import exporter as _exporter  # noqa: E402,F401

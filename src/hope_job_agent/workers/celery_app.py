"""Celery configuration with separate interactive and batch queues."""

from celery import Celery
from kombu import Queue

from hope_job_agent.platform.settings import get_platform_settings

settings = get_platform_settings()
celery_app = Celery(
    "hope_job_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["hope_job_agent.workers.tasks"],
)
celery_app.conf.update(
    task_queues=(
        Queue("interactive", routing_key="interactive"),
        Queue("batch", routing_key="batch"),
        Queue("ingest", routing_key="ingest"),
    ),
    task_routes={
        "hope.coach.*": {"queue": "interactive"},
        "hope.enrichment.*": {"queue": "batch"},
        "hope.matching.*": {"queue": "batch"},
        "hope.privacy.*": {"queue": "batch"},
        "hope.sources.*": {"queue": "ingest"},
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Local LLM inference on the Spark is slow on a cold model load; the
    # per-task overrides on source refresh raise this much further.
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=86400,
)

"""Expose Celery worker metrics to Prometheus.

The API container is instrumented by ``prometheus_fastapi_instrumentator`` and
scraped at ``/metrics``. Workers had no equivalent, so every counter in
:mod:`hope_job_agent.ai.telemetry` -- all of which are incremented on the *batch*
queue, where enrichment, embedding and matching actually run -- was written to
process memory and never read by anything.

Celery's prefork pool makes this more than a missing endpoint. Each container is
one parent plus N children, and the child that increments a counter is not the
process that can serve HTTP. ``prometheus_client`` solves that with multiprocess
mode: children write to files in ``PROMETHEUS_MULTIPROC_DIR`` and a collector in
the parent sums them at scrape time. That directory *must* be set in the
environment before the first metric is created, which is why it is configured in
compose rather than here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from celery.signals import celeryd_init, worker_process_shutdown
from prometheus_client import CollectorRegistry, multiprocess, start_http_server

LOGGER = logging.getLogger(__name__)

METRICS_PORT = int(os.getenv("WORKER_METRICS_PORT", "9100"))
MULTIPROC_ENV = "PROMETHEUS_MULTIPROC_DIR"


def _multiproc_dir() -> Path | None:
    value = os.getenv(MULTIPROC_ENV, "").strip()
    return Path(value) if value else None


@celeryd_init.connect
def start_metrics_server(**_kwargs: Any) -> None:
    """Serve the multiprocess registry from the worker parent process.

    Runs on ``celeryd_init`` (parent, once) rather than ``worker_process_init``
    (every child): N children racing for one port would leave N-1 workers dead
    on startup.
    """

    directory = _multiproc_dir()
    if directory is None:
        LOGGER.info("%s unset; worker metrics endpoint disabled", MULTIPROC_ENV)
        return
    directory.mkdir(parents=True, exist_ok=True)
    # Files survive a container restart and would otherwise be summed into the
    # new process's counters, producing impossible jumps in every rate().
    for stale in directory.glob("*.db"):
        stale.unlink(missing_ok=True)
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(METRICS_PORT, registry=registry)
    LOGGER.info("Worker metrics listening on :%d", METRICS_PORT)


@worker_process_shutdown.connect
def clear_process_metrics(pid: int | None = None, **_kwargs: Any) -> None:
    """Drop a finished child's gauge files.

    Without this, a recycled child leaves its last values behind forever and
    every ``livemostrecent`` gauge keeps reporting a sample from a process that
    no longer exists.
    """

    if _multiproc_dir() is None or pid is None:
        return
    multiprocess.mark_process_dead(pid)

"""The beat schedule is the automation contract.

This replaces scripts/validate_n8n_workflows.py, which checked that nine JSON
exports parsed and held no secrets. It could not check the thing that actually
mattered: whether the workflow pointed at something real. A typo in a task name
here is a job that silently never runs, which is exactly the failure mode the
n8n setup shipped with.
"""

from __future__ import annotations

import pytest
from celery.schedules import crontab

from hope_job_agent.workers.celery_app import celery_app
from hope_job_agent.workers.schedules import BEAT_SCHEDULE

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module", autouse=True)
def _load_tasks() -> None:
    """Import the task modules the worker would import.

    Celery registers tasks lazily from ``conf.include``; without this the
    registry is empty and the test below would pass for the wrong reason.
    """

    celery_app.loader.import_default_modules()


def test_every_scheduled_task_is_registered() -> None:
    registered = set(celery_app.tasks)
    missing = {
        name: entry["task"]
        for name, entry in BEAT_SCHEDULE.items()
        if entry["task"] not in registered
    }
    assert not missing, f"Scheduled tasks that do not exist: {missing}"


def test_every_scheduled_task_routes_to_a_consumed_queue() -> None:
    """A task routed to a queue no worker runs is enqueued and never executed.

    This is not hypothetical: hope.market.refresh matched no route and went to
    Celery's default "celery" queue, which no worker consumes.
    """

    consumed = {queue.name for queue in celery_app.conf.task_queues}
    for name, entry in BEAT_SCHEDULE.items():
        route = celery_app.amqp.router.route({}, entry["task"])
        queue = route.get("queue", celery_app.conf.task_default_queue)
        queue_name = getattr(queue, "name", queue)
        assert queue_name in consumed, f"{name} routes to unconsumed queue {queue_name}"


def test_schedule_is_wired_into_the_app() -> None:
    assert celery_app.conf.beat_schedule == BEAT_SCHEDULE


def test_local_timezone_is_set() -> None:
    """Crontabs are local so an 8 AM digest stays at 8 AM across a DST change."""

    assert celery_app.conf.timezone == "America/Indiana/Indianapolis"


def test_entries_declare_a_schedule() -> None:
    for name, entry in BEAT_SCHEDULE.items():
        schedule = entry["schedule"]
        assert isinstance(schedule, crontab | float | int), name


def test_source_sweep_runs_once_per_window() -> None:
    """One entry crawls employer boards, not two.

    The retired workflows scheduled refresh-all *and* company-careers-refresh
    on the same four-hour cadence, and refresh_all already includes
    company_careers -- so every window hit the same public ATS boards twice.
    """

    crawlers = [
        name
        for name, entry in BEAT_SCHEDULE.items()
        if entry["task"].startswith("hope.sources.")
    ]
    assert crawlers == ["refresh-all-sources"]


def test_frequent_entries_expire() -> None:
    """Sub-minute tasks must not pile up if the ops worker is down.

    Without an expiry, a worker offline for an hour comes back to 120 stale
    relay tasks and runs every one of them.
    """

    for name, entry in BEAT_SCHEDULE.items():
        schedule = entry["schedule"]
        if isinstance(schedule, float | int) and schedule <= 60:
            assert entry.get("options", {}).get("expires"), f"{name} needs an expiry"

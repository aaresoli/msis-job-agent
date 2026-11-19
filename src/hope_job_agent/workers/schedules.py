"""The platform's schedule, in code.

This replaces nine n8n workflow exports. Every one of them was a schedule
trigger wired to an HTTP POST against this application's own ``/internal/v1``
API -- no third-party connectors, which is the thing n8n exists for. In exchange
they carried a second Postgres database, a second queue engine, an encryption
key, and a service token with permission to trigger crawls and read every
student record. They also shipped ``"active": false`` and only existed inside
the container once an operator manually ran an import script, so in practice
nothing was automated at all.

Calling the tasks directly removes the HTTP hop, the bearer token, and the
idempotency-header dance, and puts the schedule somewhere it can be reviewed,
typed, and tested. :mod:`tests.test_schedules` is the check that every entry
below still names a task that exists.

Times are Indianapolis local (see ``timezone`` in celery_app), matching what the
retired workflows used. Indiana observes DST, so ``crontab`` on a local timezone
is what keeps an 8 AM digest at 8 AM year-round.
"""

from __future__ import annotations

from typing import Any

from celery.schedules import crontab

# Deliberately *not* every four hours on the hour for both the sweep and the
# reconciliation: staggering keeps a long ATS crawl from overlapping the nightly
# maintenance window.
BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    # Sources -------------------------------------------------------------
    # One sweep covers every approved source, including company_careers. The
    # retired workflows scheduled `refresh-all` *and* `company-careers-refresh`
    # on the same four-hour cadence, which crawled the same employer boards
    # twice per window.
    "refresh-all-sources": {
        "task": "hope.sources.refresh_all",
        "schedule": crontab(minute="15", hour="*/4"),
        "kwargs": {"limit": 1000, "dry_run": False},
        # A sweep that is still running when the next window opens should be
        # skipped, not stacked. Celery's own expiry is the cheap half of this;
        # the single-flight lock in the task is the half that actually holds.
        "options": {"expires": 3600},
    },
    # Delivery ------------------------------------------------------------
    "student-digests-daily": {
        "task": "hope.ops.send_digests",
        "schedule": crontab(minute="0", hour="8"),
        "kwargs": {"cadence": "daily"},
    },
    "student-digests-weekly": {
        "task": "hope.ops.send_digests",
        "schedule": crontab(minute="0", hour="8", day_of_week="1"),
        "kwargs": {"cadence": "weekly"},
    },
    "application-reminders": {
        "task": "hope.ops.application_reminders",
        "schedule": crontab(minute="30", hour="7"),
    },
    # The relay is what actually sends the mail the two digest entries above
    # queue, and it is the backstop for every other outbox event. Frequent and
    # cheap: an empty run is one indexed query.
    "relay-outbox": {
        "task": "hope.ops.relay_outbox",
        "schedule": 30.0,
        "options": {"expires": 60},
    },
    # Maintenance ---------------------------------------------------------
    "nightly-backup": {
        "task": "hope.ops.backup",
        "schedule": crontab(minute="0", hour="1"),
    },
    "nightly-reconciliation": {
        "task": "hope.ops.reconcile",
        "schedule": crontab(minute="0", hour="2"),
    },
    "privacy-retention": {
        "task": "hope.privacy.retention",
        "schedule": crontab(minute="0", hour="3"),
    },
    # Observability -------------------------------------------------------
    # Replaces the source-health-alerts workflow: the same failure query now
    # feeds a gauge, and Prometheus decides when it is worth waking someone.
    "export-metrics": {
        "task": "hope.ops.export_metrics",
        "schedule": 60.0,
        "options": {"expires": 120},
    },
    "beat-heartbeat": {
        "task": "hope.ops.heartbeat",
        "schedule": 60.0,
        "options": {"expires": 120},
    },
}

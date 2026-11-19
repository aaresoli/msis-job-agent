"""Drain the transactional outbox.

``outbox_events`` rows have been written since the platform's first commit and
were never read by anything. The table's ``published_at`` and ``attempts``
columns describe the relay that belongs here.

Why an outbox at all: the request path does ``db.add(...)`` and then
``task.apply_async(..., countdown=2)`` in the same handler. Those are two
different systems, and the enqueue happens *before* the transaction commits --
the ``countdown`` is a hand-rolled hedge against the worker picking the task up
before the row it needs exists. If the commit then rolls back, the task runs
against nothing; if the enqueue fails, the row exists with no work scheduled.
The outbox row rides the same transaction as the data, so it is the only record
of intent that cannot disagree with what was actually committed.

The relay claims work with ``FOR UPDATE ... SKIP LOCKED``, so running it on more
than one worker splits the backlog instead of double-sending it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.platform_models import OutboxEvent
from hope_job_agent.ops.digests import deliver_digest
from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

Handler = Callable[[Session, OutboxEvent], bool]


def _handle_digest_requested(db: Session, event: OutboxEvent) -> bool:
    cadence = str(event.payload.get("cadence", "daily"))
    return deliver_digest(db, user_id=UUID(event.aggregate_id), cadence=cadence)


def _already_dispatched_in_request(_db: Session, _event: OutboxEvent) -> bool:
    """Mark published without acting.

    These three events record a state change whose follow-up work is dispatched
    inline by the handler that wrote them -- ``generate_profile_matches`` at
    api/student.py, ``parse_resume`` at api/student.py, ``enrich_job`` at
    api/internal.py. Dispatching again here would double every enrichment and
    every match run.

    Losing one of those inline dispatches is covered by nightly reconciliation
    (:mod:`hope_job_agent.ops.reconcile`), which asks the database what is
    missing rather than replaying events. Do not add a re-dispatch here without
    removing the inline one first.
    """

    return False


HANDLERS: dict[str, Handler] = {
    "digest.requested.v1": _handle_digest_requested,
    "profile.updated.v1": _already_dispatched_in_request,
    "resume.uploaded.v1": _already_dispatched_in_request,
    "job.upserted.v1": _already_dispatched_in_request,
}


def relay_pending(db: Session, *, batch_size: int | None = None) -> dict[str, Any]:
    """Publish one batch of unpublished events."""

    settings = get_platform_settings()
    limit = batch_size or settings.outbox_batch_size
    max_attempts = settings.outbox_max_attempts
    events = db.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.attempts < max_attempts,
        )
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    published = 0
    delivered = 0
    failed = 0
    dead_lettered = 0
    for event in events:
        event.attempts += 1
        handler = HANDLERS.get(event.event_type)
        if handler is None:
            # An unknown type is a deploy-order problem, not a poison message:
            # a newer writer can emit an event an older relay has no handler
            # for. Leave it unpublished so the next release picks it up, and let
            # the dead-letter threshold catch a type that never gains a handler.
            LOGGER.warning("No outbox handler for %s", event.event_type)
            failed += 1
            if event.attempts >= max_attempts:
                dead_lettered += 1
            continue
        try:
            acted = handler(db, event)
        except Exception:
            # One bad recipient must not stall the queue behind it. The attempt
            # counter is already incremented, so a permanently failing event
            # dead-letters instead of retrying forever.
            LOGGER.exception(
                "Outbox handler failed for %s %s", event.event_type, event.id
            )
            failed += 1
            if event.attempts >= max_attempts:
                dead_lettered += 1
                LOGGER.error("Dead-lettering outbox event %s", event.id)
            continue
        event.published_at = datetime.now(UTC)
        published += 1
        delivered += int(acted)

    # The session factory sets autoflush=False, so without this the attempt
    # counters and published stamps stay in the identity map: a second pass in
    # the same transaction would re-claim and re-send every event just handled.
    db.flush()

    return {
        "claimed": len(events),
        "published": published,
        "delivered": delivered,
        "failed": failed,
        "dead_lettered": dead_lettered,
    }

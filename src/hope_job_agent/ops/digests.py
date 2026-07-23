"""Student digests: queue them on a schedule, deliver them from the outbox.

The two halves are deliberately separate. :func:`queue_digests` runs once per
cadence and only writes rows -- an in-app notification and an outbox event per
student -- inside the caller's transaction. :func:`deliver_digest` sends the
mail, one student at a time, driven by the relay.

Splitting them that way means a nightly run cannot be half-delivered: a crash
partway through queueing rolls back cleanly, and a crash partway through sending
leaves the remaining events unpublished for the next relay pass. Sending inline
would have made an SMTP timeout on student 40 of 200 both lose the other 160 and
double-send the first 39 on retry.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import (
    JobMatchRecord,
    JobPostingRecord,
    StudentProfileRecord,
)
from hope_job_agent.db.platform_models import Notification, OutboxEvent, User
from hope_job_agent.delivery.email_digest import build_email_digest
from hope_job_agent.delivery.smtp import send_message
from hope_job_agent.models.match import JobMatch
from hope_job_agent.persistence.mapping import job_from_record
from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

CADENCES = frozenset({"daily", "weekly"})
# A digest is a prompt to open the app, not a replacement for it.
DIGEST_MATCH_LIMIT = 10
# Only matches the platform is willing to show a student. "degraded" is included
# because a match scored without the LLM is still a real match, just without a
# generated explanation.
DELIVERABLE_STATUSES = ("ready", "degraded")


class UnsupportedCadence(ValueError):
    pass


def queue_digests(db: Session, cadence: str) -> dict[str, Any]:
    """Create a notification and an outbox event per student with matches."""

    if cadence not in CADENCES:
        raise UnsupportedCadence(f"Unsupported digest cadence: {cadence}")
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
                    JobMatchRecord.status.in_(DELIVERABLE_STATUSES),
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


def deliver_digest(db: Session, *, user_id: UUID, cadence: str) -> bool:
    """Render and send one student's digest. Returns whether mail was sent."""

    user = db.get(User, user_id)
    if user is None or user.status != "active":
        # Queued before a deletion request or a disable landed. Not an error:
        # the relay marks the event published and moves on.
        LOGGER.info("Skipping digest for missing or inactive user %s", user_id)
        return False
    profile = db.scalar(
        select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
    )
    if profile is None:
        return False
    matches = _load_matches(db, profile.id)
    if not matches:
        return False
    body = build_email_digest(profile.name or user.display_name or user.email, matches)
    message = EmailMessage()
    message["Subject"] = f"Your {cadence} HOPE career brief"
    message["To"] = user.email
    message.set_content(body)
    return send_message(message, get_platform_settings())


def _load_matches(db: Session, profile_id: UUID) -> list[JobMatch]:
    rows = db.execute(
        select(JobMatchRecord, JobPostingRecord)
        .join(JobPostingRecord, JobPostingRecord.id == JobMatchRecord.job_id)
        .where(
            JobMatchRecord.student_id == profile_id,
            JobMatchRecord.status.in_(DELIVERABLE_STATUSES),
            JobPostingRecord.status == "active",
        )
        .order_by(JobMatchRecord.match_score.desc())
        .limit(DIGEST_MATCH_LIMIT)
    ).all()
    return [
        JobMatch(
            job=job_from_record(posting),
            score=match.match_score,
            reasons=[match.explanation] if match.explanation else [],
            metadata={"status": match.status, "ranking_version": match.ranking_version},
        )
        for match, posting in rows
    ]

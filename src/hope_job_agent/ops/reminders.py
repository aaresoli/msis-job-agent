"""Application-deadline reminders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.platform_models import ApplicationRecord, Notification

REMINDER_WINDOW_DAYS = 7
# Only applications the student has not yet sent. A submitted application has
# nothing left to remind them about.
REMINDABLE_STATUSES = ("saved", "preparing")


def create_application_reminders(db: Session) -> dict[str, Any]:
    """Notify students about applications due inside the reminder window.

    Runs daily, and the same deadline therefore reminds on each of the seven
    days before it. That is intentional for a deadline the student has not acted
    on -- moving the application out of ``saved``/``preparing`` is what stops it.
    """

    today = datetime.now(UTC).date()
    upcoming = db.scalars(
        select(ApplicationRecord).where(
            ApplicationRecord.deadline.is_not(None),
            ApplicationRecord.deadline >= today,
            ApplicationRecord.deadline <= today + timedelta(days=REMINDER_WINDOW_DAYS),
            ApplicationRecord.status.in_(REMINDABLE_STATUSES),
        )
    ).all()
    for application in upcoming:
        db.add(
            Notification(
                user_id=application.user_id,
                kind="application_deadline",
                title=f"Deadline: {application.role_title}",
                body=f"{application.company_name} is due {application.deadline}.",
                action_url="/applications",
            )
        )
    return {"status": "created", "reminders": len(upcoming)}

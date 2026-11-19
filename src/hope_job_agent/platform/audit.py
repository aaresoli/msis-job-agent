"""Append-only audit logging helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from hope_job_agent.db.platform_models import AuditEvent


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    actor_user_id: UUID | None = None,
    subject_user_id: UUID | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            metadata_json=metadata,
        )
    )

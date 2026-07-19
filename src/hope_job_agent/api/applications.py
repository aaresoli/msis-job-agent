"""Student-owned application tracking routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import current_user, get_db, require_csrf
from hope_job_agent.api.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    MessageResponse,
)
from hope_job_agent.db.platform_models import ApplicationEvent, ApplicationRecord, User
from hope_job_agent.platform.audit import record_audit

router = APIRouter(prefix="/applications", tags=["applications"])


def _payload(row: ApplicationRecord) -> dict:
    return {
        "id": str(row.id),
        "job_id": str(row.job_id) if row.job_id else None,
        "company_name": row.company_name,
        "role_title": row.role_title,
        "status": row.status,
        "notes": row.notes,
        "deadline": row.deadline,
        "external_url": row.external_url,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("")
def list_applications(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(ApplicationRecord)
        .where(ApplicationRecord.user_id == user.id)
        .order_by(ApplicationRecord.updated_at.desc())
    ).all()
    return [_payload(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    row = ApplicationRecord(
        user_id=user.id,
        job_id=payload.job_id,
        company_name=payload.company_name,
        role_title=payload.role_title,
        status=payload.status,
        notes=payload.notes,
        deadline=payload.deadline,
        external_url=str(payload.external_url) if payload.external_url else None,
    )
    db.add(row)
    db.flush()
    db.add(ApplicationEvent(application_id=row.id, to_status=row.status))
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="application.created",
        resource_type="application",
        resource_id=str(row.id),
    )
    return _payload(row)


@router.patch("/{application_id}")
def update_application(
    application_id: UUID,
    payload: ApplicationUpdate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(ApplicationRecord, application_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404)
    prior = row.status
    row.status = payload.status
    row.notes = payload.notes
    row.deadline = payload.deadline
    if prior != row.status:
        db.add(
            ApplicationEvent(
                application_id=row.id, from_status=prior, to_status=row.status
            )
        )
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="application.updated",
        resource_type="application",
        resource_id=str(row.id),
        metadata={"from_status": prior, "to_status": row.status},
    )
    return _payload(row)


@router.delete("/{application_id}", response_model=MessageResponse)
def delete_application(
    application_id: UUID,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    row = db.get(ApplicationRecord, application_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404)
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="application.deleted",
        resource_type="application",
        resource_id=str(row.id),
    )
    db.delete(row)
    return MessageResponse(message="Application removed")

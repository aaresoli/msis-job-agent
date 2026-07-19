"""Student profile, consent, resume, privacy, and notification routes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import current_user, get_db, require_csrf
from hope_job_agent.api.schemas import (
    ConsentCreate,
    MessageResponse,
    ProfileUpdate,
    ResumeConfirm,
    SharingGrantCreate,
)
from hope_job_agent.db.models import StudentProfileRecord
from hope_job_agent.db.platform_models import (
    ConsentRecord,
    DeletionRequest,
    Notification,
    OutboxEvent,
    ResumeDocument,
    SharingGrant,
    User,
)
from hope_job_agent.platform.audit import record_audit
from hope_job_agent.platform.documents import put_private_document
from hope_job_agent.workers.tasks import generate_profile_matches, parse_resume

router = APIRouter(prefix="/me", tags=["student"])
MAX_RESUME_BYTES = 10 * 1024 * 1024
RESUME_MEDIA_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/profile")
def get_profile(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    profile = db.scalar(
        select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
    )
    if profile is None:
        return {"user_id": str(user.id), "email": user.email, "profile": None}
    return {
        "user_id": str(user.id),
        "email": user.email,
        "profile": profile.profile_json,
        "updated_at": profile.updated_at,
    }


@router.put("/profile")
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.scalar(
        select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
    )
    values = payload.model_dump(mode="json")
    if profile is None:
        profile = StudentProfileRecord(
            user_id=user.id,
            external_student_id=str(user.id),
            name=payload.name,
            email=user.email,
            concentration=payload.concentration,
            stage=payload.academic_stage,
            interests=payload.target_roles,
            skills=payload.skills,
            profile_json=values,
            program_exit_at=payload.program_exit_at,
        )
        db.add(profile)
    else:
        profile.name = payload.name
        profile.concentration = payload.concentration
        profile.stage = payload.academic_stage
        profile.interests = payload.target_roles
        profile.skills = payload.skills
        profile.profile_json = values
        profile.program_exit_at = payload.program_exit_at
    user.display_name = payload.name
    db.flush()
    db.add(
        OutboxEvent(
            event_type="profile.updated.v1",
            aggregate_type="student_profile",
            aggregate_id=str(profile.id),
            payload={"user_id": str(user.id)},
        )
    )
    generate_profile_matches.apply_async(args=[str(profile.id)], countdown=2)
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="profile.updated",
        resource_type="student_profile",
    )
    return {"profile": values, "status": "saved"}


@router.post("/consents", status_code=status.HTTP_201_CREATED)
def create_consent(
    payload: ConsentCreate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    consent = ConsentRecord(
        user_id=user.id,
        policy_version=payload.policy_version,
        ai_matching=payload.ai_matching,
        accepted_at=datetime.now(UTC),
    )
    db.add(consent)
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="consent.recorded",
        resource_type="consent",
        metadata=payload.model_dump(),
    )
    return {"status": "recorded", "policy_version": payload.policy_version}


@router.get("/consents")
def list_consents(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.user_id == user.id)
        .order_by(ConsentRecord.accepted_at.desc())
    ).all()
    return [
        {
            "id": str(row.id),
            "policy_version": row.policy_version,
            "ai_matching": row.ai_matching,
            "accepted_at": row.accepted_at,
            "withdrawn_at": row.withdrawn_at,
        }
        for row in rows
    ]


@router.post("/sharing-grants", status_code=status.HTTP_201_CREATED)
def create_sharing_grant(
    payload: SharingGrantCreate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    advisor = db.get(User, payload.advisor_user_id)
    if advisor is None or advisor.role not in {"gcs", "admin"}:
        raise HTTPException(status_code=400, detail="Advisor is not available")
    grant = SharingGrant(
        student_user_id=user.id,
        advisor_user_id=advisor.id,
        scope=list(payload.scope),
        expires_at=payload.expires_at,
    )
    db.add(grant)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="sharing.granted",
        resource_type="sharing_grant",
        resource_id=str(grant.id),
    )
    return {"id": str(grant.id), "expires_at": grant.expires_at}


@router.get("/sharing-grants")
def list_sharing_grants(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.execute(
        select(SharingGrant, User)
        .join(User, User.id == SharingGrant.advisor_user_id)
        .where(SharingGrant.student_user_id == user.id)
        .order_by(SharingGrant.created_at.desc())
    ).all()
    return [
        {
            "id": str(grant.id),
            "advisor": advisor.display_name or advisor.email,
            "scope": grant.scope,
            "expires_at": grant.expires_at,
            "revoked_at": grant.revoked_at,
        }
        for grant, advisor in rows
    ]


@router.delete("/sharing-grants/{grant_id}", response_model=MessageResponse)
def revoke_sharing_grant(
    grant_id: str,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    grant = db.get(SharingGrant, grant_id)
    if grant is None or grant.student_user_id != user.id:
        raise HTTPException(status_code=404)
    grant.revoked_at = datetime.now(UTC)
    return MessageResponse(message="Sharing access revoked")


@router.post("/resume", status_code=status.HTTP_202_ACCEPTED)
async def upload_resume(
    file: UploadFile = File(...),
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    if file.content_type not in RESUME_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Upload a PDF or DOCX resume")
    content = await file.read(MAX_RESUME_BYTES + 1)
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume exceeds 10 MB")
    filename = Path(file.filename or "resume").name
    digest = hashlib.sha256(content).hexdigest()
    object_key = f"resumes/{user.id}/{uuid4()}-{digest[:12]}"
    put_private_document(object_key, content, file.content_type)
    record = ResumeDocument(
        user_id=user.id,
        object_key=object_key,
        original_filename=filename,
        media_type=file.content_type,
        size_bytes=len(content),
        sha256=digest,
    )
    db.add(record)
    db.flush()
    db.add(
        OutboxEvent(
            event_type="resume.uploaded.v1",
            aggregate_type="resume",
            aggregate_id=str(record.id),
            payload={"user_id": str(user.id)},
        )
    )
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="resume.uploaded",
        resource_type="resume",
        resource_id=str(record.id),
    )
    parse_resume.apply_async(args=[str(record.id)], countdown=2)
    return {"id": str(record.id), "parse_status": record.parse_status}


@router.get("/resume/{resume_id}")
def get_resume_parse(
    resume_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    resume = db.get(ResumeDocument, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=404)
    return {
        "id": str(resume.id),
        "parse_status": resume.parse_status,
        "parsed_profile": resume.parsed_profile,
        "confirmed_at": resume.confirmed_at,
    }


@router.post("/resume/{resume_id}/confirm")
def confirm_resume(
    resume_id: str,
    payload: ResumeConfirm,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    resume = db.get(ResumeDocument, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=404)
    if resume.parse_status != "review":
        raise HTTPException(status_code=409, detail="Resume is not ready for review")
    update_profile(payload.accepted_profile, user, db)
    resume.confirmed_at = datetime.now(UTC)
    return {"id": str(resume.id), "status": "confirmed"}


@router.get("/notifications")
def list_notifications(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": str(row.id),
            "kind": row.kind,
            "title": row.title,
            "body": row.body,
            "action_url": row.action_url,
            "read_at": row.read_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/deletion", status_code=status.HTTP_202_ACCEPTED)
def request_deletion(
    user: User = Depends(require_csrf), db: Session = Depends(get_db)
) -> dict:
    request = DeletionRequest(user_id=user.id)
    db.add(request)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="privacy.deletion_requested",
        resource_type="deletion_request",
        resource_id=str(request.id),
    )
    return {"id": str(request.id), "status": request.status}


@router.get("/export")
def export_my_data(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    profile = db.scalar(
        select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
    )
    consents = db.scalars(
        select(ConsentRecord).where(ConsentRecord.user_id == user.id)
    ).all()
    return {
        "exported_at": datetime.now(UTC),
        "account": {"id": str(user.id), "email": user.email, "role": user.role},
        "profile": profile.profile_json if profile else None,
        "consents": [
            {
                "policy_version": row.policy_version,
                "ai_matching": row.ai_matching,
                "accepted_at": row.accepted_at,
                "withdrawn_at": row.withdrawn_at,
            }
            for row in consents
        ],
    }

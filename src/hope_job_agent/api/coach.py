"""Advisory-only career coach routes with server-sent event streaming."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.ai.graphs import stream_coach_reply
from hope_job_agent.ai.provider import get_model_provider
from hope_job_agent.api.dependencies import current_user, get_db, require_csrf
from hope_job_agent.api.schemas import CoachMessageCreate
from hope_job_agent.db.models import StudentProfileRecord
from hope_job_agent.db.platform_models import CoachMessage, CoachThread, User
from hope_job_agent.platform.audit import record_audit

router = APIRouter(prefix="/coach", tags=["career-coach"])


@router.get("/threads")
def list_threads(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CoachThread)
        .where(CoachThread.user_id == user.id)
        .order_by(CoachThread.updated_at.desc())
    ).all()
    return [
        {"id": str(row.id), "title": row.title, "status": row.status} for row in rows
    ]


@router.post("/threads", status_code=status.HTTP_201_CREATED)
def create_thread(
    user: User = Depends(require_csrf), db: Session = Depends(get_db)
) -> dict[str, Any]:
    thread = CoachThread(user_id=user.id)
    db.add(thread)
    db.flush()
    return {"id": str(thread.id), "title": thread.title}


@router.get("/threads/{thread_id}/messages")
def list_messages(
    thread_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    thread = db.get(CoachThread, thread_id)
    if thread is None or thread.user_id != user.id:
        raise HTTPException(status_code=404)
    rows = db.scalars(
        select(CoachMessage)
        .where(CoachMessage.thread_id == thread_id)
        .order_by(CoachMessage.created_at)
    ).all()
    return [
        {
            "id": str(row.id),
            "role": row.role,
            "content": row.content,
            "citations": row.citations or [],
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/threads/{thread_id}/messages")
def stream_message(
    thread_id: UUID,
    payload: CoachMessageCreate,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    thread = db.get(CoachThread, thread_id)
    if thread is None or thread.user_id != user.id:
        raise HTTPException(status_code=404)
    profile = db.scalar(
        select(StudentProfileRecord).where(StudentProfileRecord.user_id == user.id)
    )
    db.add(CoachMessage(thread_id=thread_id, role="user", content=payload.content))
    db.flush()
    profile_context = profile.profile_json if profile else {}

    def events() -> Iterator[str]:
        chunks: list[str] = []
        for chunk in stream_coach_reply(
            get_model_provider(), payload.content, {"profile": profile_context}
        ):
            chunks.append(chunk)
            yield f"event: token\ndata: {json.dumps({'text': chunk})}\n\n"
        db.add(
            CoachMessage(thread_id=thread_id, role="assistant", content="".join(chunks))
        )
        record_audit(
            db,
            actor_user_id=user.id,
            subject_user_id=user.id,
            action="coach.responded",
            resource_type="coach_thread",
            resource_id=str(thread_id),
        )
        # The get_db dependency commits at teardown, but that runs only after
        # the response body is fully consumed. Commit here so the turn is
        # durable even if the client disconnects mid-stream.
        db.commit()
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

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

from hope_job_agent.ai.graphs import CoachStreamStatus, stream_coach_reply
from hope_job_agent.ai.provider import WORKLOAD_INTERACTIVE, get_model_provider
from hope_job_agent.api.coach_context import build_coach_context, verified_citations
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
    provider = get_model_provider(WORKLOAD_INTERACTIVE)
    # Retrieval runs before the stream opens, so a slow lookup shows up as
    # latency to first token rather than a stall partway through the answer.
    context = build_coach_context(
        db,
        user_id=user.id,
        profile_id=profile.id if profile else None,
        profile_json=profile.profile_json if profile else {},
        question=payload.content,
        provider=provider,
    )

    def events() -> Iterator[str]:
        chunks: list[str] = []
        stream_status = CoachStreamStatus()
        for chunk in stream_coach_reply(
            provider,
            payload.content,
            context.payload,
            status=stream_status,
        ):
            chunks.append(chunk)
            yield f"event: token\ndata: {json.dumps({'text': chunk})}\n\n"
        reply = "".join(chunks)
        # Only postings that were actually in context are stored as citations;
        # an invented job_id is dropped rather than persisted as a source.
        citations = verified_citations(reply, context.citable)
        # A stream cut short by an outage is stored with its inline notice
        # attached, never as a clean turn: thread history is what the student
        # rereads later, and a silently truncated answer there is indistinguish-
        # able from advice the coach actually finished giving.
        db.add(
            CoachMessage(
                thread_id=thread_id,
                role="assistant",
                content=reply,
                citations=citations,
            )
        )
        record_audit(
            db,
            actor_user_id=user.id,
            subject_user_id=user.id,
            action=(
                "coach.responded.truncated"
                if stream_status.truncated
                else "coach.responded"
            ),
            resource_type="coach_thread",
            resource_id=str(thread_id),
        )
        # The get_db dependency commits at teardown, but that runs only after
        # the response body is fully consumed. Commit here so the turn is
        # durable even if the client disconnects mid-stream.
        db.commit()
        yield (
            "event: done\ndata: "
            + json.dumps({"truncated": stream_status.truncated})
            + "\n\n"
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

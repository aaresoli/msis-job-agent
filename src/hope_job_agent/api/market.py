"""Cited hiring-intelligence routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import current_user, get_db
from hope_job_agent.db.platform_models import MarketPost, MarketSignal, User

router = APIRouter(prefix="/market-pulse", tags=["market-pulse"])


@router.get("")
def list_signals(
    company: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    del user
    statement = select(MarketSignal).order_by(MarketSignal.created_at.desc())
    if company:
        statement = statement.where(MarketSignal.company_name.ilike(f"%{company}%"))
    signals = db.scalars(statement.limit(limit)).all()
    post_ids = {post_id for signal in signals for post_id in signal.citation_post_ids}
    posts = (
        db.scalars(select(MarketPost).where(MarketPost.id.in_(post_ids))).all()
        if post_ids
        else []
    )
    citations = {
        str(post.id): {
            "title": post.author_name or post.company_name or "Source post",
            "url": post.source_url,
            "published_at": post.published_at,
        }
        for post in posts
    }
    return {
        "items": [
            {
                "id": str(signal.id),
                "topic": signal.topic,
                "summary": signal.summary,
                "company_name": signal.company_name,
                "role_tags": signal.role_tags or [],
                "confidence": signal.confidence,
                "valid_until": signal.valid_until,
                "created_at": signal.created_at,
                "citations": [
                    citations[post_id]
                    for post_id in signal.citation_post_ids
                    if post_id in citations
                ],
            }
            for signal in signals
        ]
    }

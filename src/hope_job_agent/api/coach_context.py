"""Retrieval that gives the career coach something to actually reason about.

The coach prompt has always instructed the model to "cite job IDs when
relevant", but the route supplied only the student's profile -- no jobs, no
matches, no signals. The instruction was therefore unsatisfiable, and any job
the model named was necessarily invented.

This module assembles the grounding: the student's own ranked matches, postings
retrieved by semantic similarity to the question, their open applications, and
live market signals. It also returns the set of job IDs that context contains,
which is what makes a citation checkable rather than decorative.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.ai.provider import ModelProvider, ModelUnavailable
from hope_job_agent.config.database import embedding_dimension
from hope_job_agent.db.models import JobMatchRecord, JobPostingRecord
from hope_job_agent.db.platform_models import ApplicationRecord, MarketSignal
from hope_job_agent.persistence.embedding_repository import EmbeddingRepository
from hope_job_agent.platform.settings import get_platform_settings

# Mirrors EMBED_QUERY_PREFIX in workers.tasks: embeddinggemma is trained with
# task prefixes and does not apply them itself, and a question is a query.
EMBED_QUERY_PREFIX = "task: search result | query: "

TOP_MATCHES = 8
RETRIEVED_JOBS = 6
OPEN_APPLICATIONS = 10
LIVE_SIGNALS = 5
SIGNAL_SUMMARY_CHARS = 600

# Matches a bare UUID anywhere in the reply, which is how the model is asked to
# cite. Case-insensitive because models routinely re-case a hex string.
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


@dataclass
class CoachContext:
    """Everything the coach may reason from, plus what it may cite."""

    payload: dict[str, Any] = field(default_factory=dict)
    citable: dict[str, dict[str, str]] = field(default_factory=dict)


def build_coach_context(
    db: Session,
    *,
    user_id: uuid.UUID,
    profile_id: uuid.UUID | None,
    profile_json: dict[str, Any] | None,
    question: str,
    provider: ModelProvider,
) -> CoachContext:
    """Assemble grounded context for one coach question.

    Retrieval is best-effort by design: a local-model outage must degrade the
    coach to profile-only advice, never fail the request. The student is
    already mid-conversation when this runs.
    """

    citable: dict[str, dict[str, str]] = {}
    payload: dict[str, Any] = {"profile": profile_json or {}}

    matches = _top_matches(db, profile_id)
    _register(citable, matches)
    payload["your_matches"] = matches

    retrieved = _semantically_similar_jobs(db, question, provider, exclude=set(citable))
    _register(citable, retrieved)
    payload["related_postings"] = retrieved

    payload["your_applications"] = _open_applications(db, user_id)
    payload["market_signals"] = _live_signals(db)
    return CoachContext(payload=payload, citable=citable)


def _register(
    citable: dict[str, dict[str, str]], entries: list[dict[str, Any]]
) -> None:
    for entry in entries:
        job_id = str(entry.get("job_id") or "")
        if job_id:
            citable[job_id] = {
                "job_id": job_id,
                "title": str(entry.get("title") or ""),
                "company": str(entry.get("company") or ""),
            }


def _top_matches(db: Session, profile_id: uuid.UUID | None) -> list[dict[str, Any]]:
    if profile_id is None:
        return []
    rows = db.execute(
        select(JobMatchRecord, JobPostingRecord)
        .join(JobPostingRecord, JobPostingRecord.id == JobMatchRecord.job_id)
        .where(JobMatchRecord.student_id == profile_id)
        .order_by(JobMatchRecord.match_score.desc())
        .limit(TOP_MATCHES)
    ).all()
    return [
        {
            "job_id": str(job.id),
            "title": job.title,
            "company": job.company_name,
            "location": job.location,
            "match_score": round(match.match_score, 1),
            "why": match.explanation,
        }
        for match, job in rows
    ]


def _semantically_similar_jobs(
    db: Session,
    question: str,
    provider: ModelProvider,
    *,
    exclude: set[str],
) -> list[dict[str, Any]]:
    """Retrieve postings close to the question itself.

    This is what lets the coach answer "what else should I look at?" with
    something other than the same ranked list the student already sees.
    """

    settings = get_platform_settings()
    try:
        vectors = provider.embed([EMBED_QUERY_PREFIX + question])
    except ModelUnavailable:
        return []
    if not vectors or len(vectors[0]) != embedding_dimension():
        return []
    results = EmbeddingRepository(db).similarity_search(
        vectors[0],
        filters={"status": "active"},
        limit=RETRIEVED_JOBS + len(exclude),
        embedding_model=settings.ollama_embedding_model,
    )
    retrieved: list[dict[str, Any]] = []
    for job, similarity in results:
        if str(job.id) in exclude:
            continue
        retrieved.append(
            {
                "job_id": str(job.id),
                "title": job.title,
                "company": job.company_name,
                "location": job.location,
                "similarity": round(similarity, 3),
            }
        )
        if len(retrieved) >= RETRIEVED_JOBS:
            break
    return retrieved


def _open_applications(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ApplicationRecord)
        .where(ApplicationRecord.user_id == user_id)
        .order_by(ApplicationRecord.updated_at.desc())
        .limit(OPEN_APPLICATIONS)
    ).all()
    return [
        {"job_id": str(row.job_id) if row.job_id else None, "status": row.status}
        for row in rows
    ]


def _live_signals(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(MarketSignal)
        .where(
            (MarketSignal.valid_until.is_(None))
            | (MarketSignal.valid_until >= datetime.now(UTC))
        )
        .order_by(MarketSignal.created_at.desc())
        .limit(LIVE_SIGNALS)
    ).all()
    return [
        {
            "topic": row.topic,
            # market_signals.summary allows 10k characters. Five of those would
            # alone exceed the budget coach_messages truncates the whole
            # context to, silently pushing the student's own matches out of the
            # prompt in favour of general market prose.
            "summary": row.summary[:SIGNAL_SUMMARY_CHARS],
            "company": row.company_name,
            "confidence": row.confidence,
        }
        for row in rows
    ]


def verified_citations(
    reply: str, citable: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    """Return the citations in ``reply`` that point at supplied postings.

    A streamed answer cannot be retracted once tokens have shipped, so this
    does not police the prose -- it decides what gets *stored* as a citation.
    An ID the model invented is simply absent from the allowlist and is
    dropped, which keeps the thread history honest about what was grounded.
    """

    seen: dict[str, dict[str, str]] = {}
    for candidate in _UUID_PATTERN.findall(reply):
        entry = citable.get(candidate.casefold())
        if entry is not None:
            seen[candidate.casefold()] = entry
    return list(seen.values())

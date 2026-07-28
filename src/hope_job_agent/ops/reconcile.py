"""Nightly reconciliation for work that is missing or stale.

Dispatches can be lost when a worker or transaction dies. Embeddings can also
become stale when the source text, canonical prompt, or configured model
changes. Reconciliation derives required work from current database state so
all of those cases heal without replaying historical events.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.ai.embeddings import (
    document_embedding_text,
    embedding_input_hash,
)
from hope_job_agent.db.models import (
    JobEmbedding,
    JobPostingRecord,
    StudentProfileRecord,
)
from hope_job_agent.db.platform_models import JobEnrichment
from hope_job_agent.platform.settings import get_platform_settings

RECONCILE_LIMIT = 1000
ENRICHMENT_VERSION = "enrichment-v1"


def find_reconciliation_backlog(
    db: Session, *, embedding_model: str | None = None
) -> dict[str, list[str]]:
    """Return ids whose enrichment, embedding, or matching work is stale."""

    active_embedding_model = embedding_model or get_platform_settings().embedding_model
    unenriched = db.scalars(
        select(JobPostingRecord.id)
        .outerjoin(
            JobEnrichment,
            (JobEnrichment.job_id == JobPostingRecord.id)
            & (JobEnrichment.version == ENRICHMENT_VERSION),
        )
        .where(JobPostingRecord.status == "active", JobEnrichment.id.is_(None))
        .limit(RECONCILE_LIMIT)
    ).all()

    embedding_rows = db.execute(
        select(JobPostingRecord, JobEmbedding)
        .outerjoin(JobEmbedding, JobEmbedding.job_id == JobPostingRecord.id)
        .where(JobPostingRecord.status == "active")
        .limit(RECONCILE_LIMIT)
    ).all()
    unembedded: list[str] = []
    for job, embedding in embedding_rows:
        model_input = document_embedding_text(job.title, job.description or "")
        digest = embedding_input_hash(model_input)
        if (
            embedding is None
            or embedding.embedding_model != active_embedding_model
            or embedding.embedding_input_hash != digest
        ):
            unembedded.append(str(job.id))

    profiles = db.scalars(select(StudentProfileRecord.id).limit(RECONCILE_LIMIT)).all()
    return {
        "unenriched": [str(item) for item in unenriched],
        "unembedded": unembedded,
        "profiles": [str(item) for item in profiles],
    }


def summarize(backlog: dict[str, list[str]]) -> dict[str, Any]:
    return {key: len(value) for key, value in backlog.items()}

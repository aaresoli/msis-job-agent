"""Nightly reconciliation: re-enqueue work that never landed.

Enrichment, embedding and matching are all dispatched inline when a posting or a
profile changes. Any of those dispatches can be lost -- a worker killed
mid-task, a transaction that rolled back after the enqueue, a source refresh
that timed out. Nothing in the request path notices, because the request already
returned.

This closes the gap by asking the database what is *missing* rather than
replaying what happened. Postings without an enrichment row and postings without
a vector are tracked separately on purpose: the two backlogs drift apart
whenever an enrichment lands in review, and closing only one leaves similarity
search permanently short of the corpus.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import (
    JobEmbedding,
    JobPostingRecord,
    StudentProfileRecord,
)
from hope_job_agent.db.platform_models import JobEnrichment

RECONCILE_LIMIT = 1000
ENRICHMENT_VERSION = "enrichment-v1"


def find_reconciliation_backlog(db: Session) -> dict[str, list[str]]:
    """Return the ids of postings and profiles whose work is missing."""

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
    unembedded = db.scalars(
        select(JobPostingRecord.id)
        .outerjoin(JobEmbedding, JobEmbedding.job_id == JobPostingRecord.id)
        .where(JobPostingRecord.status == "active", JobEmbedding.id.is_(None))
        .limit(RECONCILE_LIMIT)
    ).all()
    profiles = db.scalars(select(StudentProfileRecord.id).limit(RECONCILE_LIMIT)).all()
    return {
        "unenriched": [str(item) for item in unenriched],
        "unembedded": [str(item) for item in unembedded],
        "profiles": [str(item) for item in profiles],
    }


def summarize(backlog: dict[str, list[str]]) -> dict[str, Any]:
    return {key: len(value) for key, value in backlog.items()}

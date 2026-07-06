"""Job embedding persistence repository."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import JobEmbedding, JobPostingRecord


class EmbeddingRepository:
    """Store and search pgvector embeddings."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_embedding(
        self,
        job_id: uuid.UUID | str,
        vector: list[float],
        model: str,
        input_hash: str,
    ) -> JobEmbedding:
        """Insert or update one job embedding."""

        resolved_id = _coerce_uuid(job_id)
        existing = self._session.scalar(
            select(JobEmbedding).where(JobEmbedding.job_id == resolved_id)
        )
        if existing is None:
            embedding = JobEmbedding(
                job_id=resolved_id,
                embedding=vector,
                embedding_model=model,
                embedding_input_hash=input_hash,
            )
            self._session.add(embedding)
            self._session.flush()
            return embedding

        existing.embedding = vector
        existing.embedding_model = model
        existing.embedding_input_hash = input_hash
        self._session.flush()
        return existing

    def similarity_search(
        self,
        vector: list[float],
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[tuple[JobPostingRecord, float]]:
        """Return top jobs by cosine similarity to ``vector``."""

        filters = filters or {}
        distance = JobEmbedding.embedding.cosine_distance(vector)
        stmt = (
            select(JobPostingRecord, distance.label("distance"))
            .join(JobEmbedding, JobEmbedding.job_id == JobPostingRecord.id)
            .order_by(distance.asc())
            .limit(limit)
        )
        if source := filters.get("source"):
            stmt = stmt.where(JobPostingRecord.source == source)
        if status := filters.get("status"):
            stmt = stmt.where(JobPostingRecord.status == status)
        if company := filters.get("company"):
            stmt = stmt.where(JobPostingRecord.company_name.ilike(f"%{company}%"))
        if location := filters.get("location"):
            stmt = stmt.where(JobPostingRecord.location.ilike(f"%{location}%"))
        if concentration := filters.get("concentration"):
            stmt = stmt.where(
                JobPostingRecord.concentration_tags.contains([concentration])
            )

        results: list[tuple[JobPostingRecord, float]] = []
        for row in self._session.execute(stmt):
            job = row[0]
            distance_value = float(row[1])
            similarity = 1.0 - distance_value
            results.append((job, similarity))
        return results


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))

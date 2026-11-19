"""Job embedding persistence repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import JobEmbedding, JobPostingRecord


class EmbeddingRepository:
    """Store and search pgvector embeddings."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_embedding(self, job_id: uuid.UUID | str) -> JobEmbedding | None:
        """Return the stored embedding for ``job_id``, if there is one.

        Lets a batch caller skip work whose input text and model are unchanged
        without re-embedding to find out.
        """

        return self._session.scalar(
            select(JobEmbedding).where(JobEmbedding.job_id == _coerce_uuid(job_id))
        )

    def get_embeddings(
        self, job_ids: Sequence[uuid.UUID | str]
    ) -> dict[uuid.UUID, JobEmbedding]:
        """Return stored embeddings for ``job_ids``, keyed by job id.

        The batch form of :meth:`get_embedding`, so a caller deciding which of
        many postings still need work pays one query rather than one per
        posting.
        """

        if not job_ids:
            return {}
        resolved = [_coerce_uuid(job_id) for job_id in job_ids]
        rows = self._session.scalars(
            select(JobEmbedding).where(JobEmbedding.job_id.in_(resolved))
        ).all()
        return {row.job_id: row for row in rows}

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
        embedding_model: str | None = None,
    ) -> list[tuple[JobPostingRecord, float]]:
        """Return top jobs by cosine similarity to ``vector``.

        ``embedding_model`` restricts the search to vectors produced by that
        model. Distances between two different embedding models are arithmetic
        without meaning, and the width check at the call site cannot catch it --
        ``nomic-embed-text`` and ``embeddinggemma`` are both 768-dimensional, so
        swapping one for the other would silently return nonsense rankings
        rather than fail. Passing the active model makes the mismatch show up as
        missing results, which is diagnosable.
        """

        filters = filters or {}
        distance = JobEmbedding.embedding.cosine_distance(vector)
        stmt = (
            select(JobPostingRecord, distance.label("distance"))
            .join(JobEmbedding, JobEmbedding.job_id == JobPostingRecord.id)
            .order_by(distance.asc())
            .limit(limit)
        )
        if embedding_model:
            stmt = stmt.where(JobEmbedding.embedding_model == embedding_model)
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

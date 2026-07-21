"""Add an HNSW index on job embeddings for cosine similarity search.

``EmbeddingRepository.similarity_search`` orders by ``embedding <=> :query``.
With no index backing that operator, Postgres reads every row in
``job_embeddings`` and sorts the whole set on each call, so match generation
degraded linearly as the corpus grew.

HNSW rather than IVFFlat: it needs no training pass over existing data (the
table is empty on a fresh install and grows continuously), and it keeps recall
high without an index rebuild as rows accumulate.

``vector_cosine_ops`` must match the query operator. ``cosine_distance`` in
the repository emits ``<=>``; an L2 or inner-product index would be ignored.

Revision ID: 004_embedding_hnsw
Revises: 003_job_json
"""

from __future__ import annotations

from alembic import op

revision = "004_embedding_hnsw"
down_revision = "003_job_json"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_job_embeddings_embedding_hnsw"


def upgrade() -> None:
    # m / ef_construction are pgvector's defaults, stated explicitly so a
    # future tuning change is a visible diff rather than a silent default shift.
    op.execute(f"""
        CREATE INDEX {INDEX_NAME}
        ON job_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

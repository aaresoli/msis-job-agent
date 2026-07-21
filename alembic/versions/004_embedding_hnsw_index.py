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
    # CONCURRENTLY, in an autocommit block: a plain CREATE INDEX holds a SHARE
    # lock for the whole build, which blocks every INSERT and UPDATE on
    # job_embeddings. An HNSW build over a populated table is slow, so on a
    # deployed instance that is an ingestion outage for the duration. Postgres
    # rejects CONCURRENTLY inside a transaction, and Alembic wraps migrations
    # in one, hence the explicit autocommit block.
    #
    # IF NOT EXISTS because a failed CONCURRENTLY build leaves an invalid index
    # behind rather than rolling back; see the runbook note in downgrade().
    #
    # m / ef_construction are pgvector's defaults, stated explicitly so a
    # future tuning change is a visible diff rather than a silent default shift.
    with op.get_context().autocommit_block():
        op.execute(f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME}
            ON job_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            """)


def downgrade() -> None:
    # Also CONCURRENTLY, for the same reason. This doubles as the recovery step
    # if an interrupted upgrade left an invalid index: drop it, then re-run.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")

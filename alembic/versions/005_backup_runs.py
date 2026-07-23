"""Record every backup attempt, its verification, and where the archive landed.

Backups previously existed only as an n8n workflow calling an endpoint that
returned ``{"status": "recorded"}`` without taking one. Replacing that with a
real ``pg_dumpall`` needs somewhere durable to record the result: the staleness
alert asks "when did a backup last verify?", and an in-process Prometheus gauge
answers that wrongly after any worker restart.

``verified`` is separate from ``status`` on purpose. A dump that uploaded
cleanly but failed to restore is a *worse* state than a dump that failed
outright, because it looks like protection and is not.

Revision ID: 005_backup_runs
Revises: 004_embedding_hnsw
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005_backup_runs"
down_revision = "004_embedding_hnsw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="running"
        ),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("verified_tables", postgresql.JSONB(), nullable=True),
        sa.Column("pruned_objects", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    # The staleness query is "most recent verified backup", so it reads this
    # index rather than sorting the whole table.
    op.create_index("ix_backup_runs_finished_at", "backup_runs", ["finished_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_finished_at", table_name="backup_runs")
    op.drop_table("backup_runs")

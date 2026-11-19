"""Add identity, privacy, career workflow, and local-AI platform tables.

Revision ID: 002_career_platform
Revises: 001_initial_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from hope_job_agent.db import platform_models  # noqa: F401
from hope_job_agent.db.base import Base

revision = "002_career_platform"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None

PLATFORM_TABLES = [
    "users",
    "auth_identities",
    "login_tokens",
    "user_sessions",
    "consent_records",
    "sharing_grants",
    "audit_events",
    "deletion_requests",
    "resume_documents",
    "job_enrichments",
    "saved_jobs",
    "applications",
    "application_events",
    "match_feedback",
    "notifications",
    "market_posts",
    "market_signals",
    "coach_threads",
    "coach_messages",
    "source_webhook_receipts",
    "source_quarantine_records",
    "outbox_events",
    "idempotency_records",
]


def _create_model_table(name: str) -> None:
    """Create a frozen v0.2 model table against the current migration bind."""

    table = Base.metadata.tables[name]
    table.create(bind=op.get_bind(), checkfirst=True)


def upgrade() -> None:
    _create_model_table("users")
    op.add_column(
        "student_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_student_profiles_user",
        "student_profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_student_profiles_user_id", "student_profiles", ["user_id"]
    )
    op.add_column(
        "student_profiles",
        sa.Column("program_exit_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job_matches",
        sa.Column(
            "ranking_version",
            sa.String(length=64),
            nullable=False,
            server_default="hybrid-v1",
        ),
    )
    op.add_column("job_matches", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "job_matches",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
    )
    op.execute("TRUNCATE TABLE job_embeddings")
    op.alter_column(
        "job_embeddings",
        "embedding",
        existing_type=Vector(1536),
        type_=Vector(768),
        postgresql_using="embedding::vector(768)",
    )
    for name in PLATFORM_TABLES[1:]:
        _create_model_table(name)


def downgrade() -> None:
    for name in reversed(PLATFORM_TABLES[1:]):
        op.drop_table(name)
    op.alter_column(
        "job_embeddings",
        "embedding",
        existing_type=Vector(768),
        type_=Vector(1536),
        postgresql_using="embedding::vector(1536)",
    )
    op.drop_column("job_matches", "status")
    op.drop_column("job_matches", "confidence")
    op.drop_column("job_matches", "ranking_version")
    op.drop_constraint(
        "uq_student_profiles_user_id", "student_profiles", type_="unique"
    )
    op.drop_constraint(
        "fk_student_profiles_user", "student_profiles", type_="foreignkey"
    )
    op.drop_column("student_profiles", "program_exit_at")
    op.drop_column("student_profiles", "user_id")
    op.drop_table("users")

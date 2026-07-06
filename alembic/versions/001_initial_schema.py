"""Initial PostgreSQL schema with pgvector."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

EMBED_DIM = int(os.getenv("EMBEDDING_DIMENSION", "1536"))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False, unique=True),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("website_url", sa.String(length=2048)),
        sa.Column("careers_url", sa.String(length=2048)),
        sa.Column("ats_provider", sa.String(length=64)),
        sa.Column("ats_slug", sa.String(length=256)),
        sa.Column("industry", sa.String(length=256)),
        sa.Column("headquarters", sa.String(length=256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
    op.create_index("ix_companies_ats_provider", "companies", ["ats_provider"])

    op.create_table(
        "job_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("config", postgresql.JSONB()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "source_type", name="uq_job_sources"),
    )

    op.create_table(
        "source_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("run_status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("jobs_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_deduped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["source_id"], ["job_sources.id"]),
    )
    op.create_index("ix_source_runs_source_name", "source_runs", ["source_name"])
    op.create_index("ix_source_runs_started_at", "source_runs", ["started_at"])
    op.create_index("ix_source_runs_run_status", "source_runs", ["run_status"])

    op.create_table(
        "job_postings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_job_id", sa.String(length=256)),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("source_detail", sa.String(length=128)),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("company_id", postgresql.UUID(as_uuid=True)),
        sa.Column("company_name", sa.String(length=512), nullable=False),
        sa.Column("normalized_company_name", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("description_hash", sa.String(length=128)),
        sa.Column("location", sa.String(length=512)),
        sa.Column("normalized_location", sa.String(length=512)),
        sa.Column("remote_status", sa.String(length=32)),
        sa.Column("employment_type", sa.String(length=32)),
        sa.Column("seniority", sa.String(length=32)),
        sa.Column("posted_at", sa.Date()),
        sa.Column("application_deadline", sa.Date()),
        sa.Column("source_url", sa.String(length=2048)),
        sa.Column("apply_url", sa.String(length=2048)),
        sa.Column("department", sa.String(length=256)),
        sa.Column("team", sa.String(length=256)),
        sa.Column("compensation", sa.String(length=256)),
        sa.Column("required_qualifications", sa.Text()),
        sa.Column("preferred_qualifications", sa.Text()),
        sa.Column("concentration_tags", postgresql.JSONB()),
        sa.Column("msis_relevance_score", sa.Float()),
        sa.Column("matched_keywords", postgresql.JSONB()),
        sa.Column("opt_cpt_flag", sa.Boolean()),
        sa.Column("opt_cpt_notes", sa.Text()),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="active"
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_metadata", postgresql.JSONB()),
        sa.Column("canonical_url", sa.String(length=2048)),
        sa.Column("canonical_fingerprint", sa.String(length=128)),
        sa.Column("content_hash", sa.String(length=128)),
        sa.ForeignKeyConstraint(["source_run_id"], ["source_runs.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
    )
    op.create_index("ix_job_postings_source", "job_postings", ["source"])
    op.create_index("ix_job_postings_source_detail", "job_postings", ["source_detail"])
    op.create_index(
        "ix_job_postings_external_job_id", "job_postings", ["external_job_id"]
    )
    op.create_index("ix_job_postings_company_name", "job_postings", ["company_name"])
    op.create_index(
        "ix_job_postings_normalized_company_name",
        "job_postings",
        ["normalized_company_name"],
    )
    op.create_index("ix_job_postings_title", "job_postings", ["title"])
    op.create_index(
        "ix_job_postings_normalized_title", "job_postings", ["normalized_title"]
    )
    op.create_index("ix_job_postings_location", "job_postings", ["location"])
    op.create_index("ix_job_postings_posted_at", "job_postings", ["posted_at"])
    op.create_index("ix_job_postings_fetched_at", "job_postings", ["fetched_at"])
    op.create_index("ix_job_postings_status", "job_postings", ["status"])
    op.create_index(
        "ix_job_postings_msis_relevance_score",
        "job_postings",
        ["msis_relevance_score"],
    )
    op.create_index(
        "ix_job_postings_canonical_fingerprint",
        "job_postings",
        ["canonical_fingerprint"],
    )
    op.create_index("ix_job_postings_content_hash", "job_postings", ["content_hash"])
    op.create_index(
        "ix_job_postings_source_external",
        "job_postings",
        ["source", "external_job_id"],
    )
    op.create_index(
        "uq_job_postings_source_external",
        "job_postings",
        ["source", "external_job_id"],
        unique=True,
        postgresql_where=sa.text("external_job_id IS NOT NULL"),
    )
    op.create_index(
        "uq_job_postings_canonical_url",
        "job_postings",
        ["canonical_url"],
        unique=True,
        postgresql_where=sa.text("canonical_url IS NOT NULL"),
    )

    op.create_table(
        "job_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_input_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_job_embeddings_job_id", "job_embeddings", ["job_id"])
    op.create_index(
        "ix_job_embeddings_embedding_model",
        "job_embeddings",
        ["embedding_model"],
    )

    op.create_table(
        "student_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_student_id", sa.String(length=128), unique=True),
        sa.Column("name", sa.String(length=256)),
        sa.Column("email", sa.String(length=256)),
        sa.Column("concentration", sa.String(length=256)),
        sa.Column("stage", sa.String(length=128)),
        sa.Column("interests", postgresql.JSONB()),
        sa.Column("skills", postgresql.JSONB()),
        sa.Column("profile_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "job_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True)),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("llm_score", sa.Float()),
        sa.Column("vector_score", sa.Float()),
        sa.Column("rule_score", sa.Float()),
        sa.Column("explanation", sa.Text()),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["student_id"], ["student_profiles.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"]),
    )


def downgrade() -> None:
    op.drop_table("job_matches")
    op.drop_table("student_profiles")
    op.drop_table("job_embeddings")
    op.drop_table("job_postings")
    op.drop_table("source_runs")
    op.drop_table("job_sources")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS vector")

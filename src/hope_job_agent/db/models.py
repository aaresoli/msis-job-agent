"""SQLAlchemy ORM models for PostgreSQL persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hope_job_agent.config.database import embedding_dimension
from hope_job_agent.db.base import Base

EMBED_DIM = embedding_dimension()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    normalized_name: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    website_url: Mapped[str | None] = mapped_column(String(2048))
    careers_url: Mapped[str | None] = mapped_column(String(2048))
    ats_provider: Mapped[str | None] = mapped_column(String(64), index=True)
    ats_slug: Mapped[str | None] = mapped_column(String(256))
    industry: Mapped[str | None] = mapped_column(String(256))
    headquarters: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    job_postings: Mapped[list[JobPostingRecord]] = relationship(
        back_populates="company"
    )


class JobSource(Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("name", "source_type", name="uq_job_sources"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_sources.id")
    )
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jobs_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_deduped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class JobPostingRecord(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        Index("ix_job_postings_source_external", "source", "external_job_id"),
        Index("ix_job_postings_canonical_fingerprint", "canonical_fingerprint"),
        Index("ix_job_postings_content_hash", "content_hash"),
        Index(
            "uq_job_postings_source_external",
            "source",
            "external_job_id",
            unique=True,
            postgresql_where=text("external_job_id IS NOT NULL"),
        ),
        Index(
            "uq_job_postings_canonical_url",
            "canonical_url",
            unique=True,
            postgresql_where=text("canonical_url IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_job_id: Mapped[str | None] = mapped_column(String(256), index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_detail: Mapped[str | None] = mapped_column(String(128), index=True)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_runs.id")
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id")
    )
    company_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    normalized_company_name: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    normalized_title: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    description_hash: Mapped[str | None] = mapped_column(String(128))
    location: Mapped[str | None] = mapped_column(String(512), index=True)
    normalized_location: Mapped[str | None] = mapped_column(String(512))
    remote_status: Mapped[str | None] = mapped_column(String(32))
    employment_type: Mapped[str | None] = mapped_column(String(32))
    seniority: Mapped[str | None] = mapped_column(String(32))
    posted_at: Mapped[date | None] = mapped_column(Date, index=True)
    application_deadline: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    department: Mapped[str | None] = mapped_column(String(256))
    team: Mapped[str | None] = mapped_column(String(256))
    compensation: Mapped[str | None] = mapped_column(String(256))
    required_qualifications: Mapped[str | None] = mapped_column(Text)
    preferred_qualifications: Mapped[str | None] = mapped_column(Text)
    concentration_tags: Mapped[list[str] | None] = mapped_column(JSONB)
    msis_relevance_score: Mapped[float | None] = mapped_column(Float, index=True)
    matched_keywords: Mapped[list[str] | None] = mapped_column(JSONB)
    opt_cpt_flag: Mapped[bool | None] = mapped_column(Boolean)
    opt_cpt_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    canonical_fingerprint: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str | None] = mapped_column(String(128))

    company: Mapped[Company | None] = relationship(back_populates="job_postings")
    embedding: Mapped[JobEmbedding | None] = relationship(
        back_populates="job", uselist=False
    )


class JobEmbedding(Base):
    __tablename__ = "job_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    embedding_input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    job: Mapped[JobPostingRecord] = relationship(back_populates="embedding")


class StudentProfileRecord(Base):
    __tablename__ = "student_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_student_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    name: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    concentration: Mapped[str | None] = mapped_column(String(256))
    stage: Mapped[str | None] = mapped_column(String(128))
    interests: Mapped[list[str] | None] = mapped_column(JSONB)
    skills: Mapped[list[str] | None] = mapped_column(JSONB)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class JobMatchRecord(Base):
    __tablename__ = "job_matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_profiles.id")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_postings.id"), nullable=False
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    llm_score: Mapped[float | None] = mapped_column(Float)
    vector_score: Mapped[float | None] = mapped_column(Float)
    rule_score: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

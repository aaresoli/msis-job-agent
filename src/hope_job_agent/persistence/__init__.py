"""Persistence layer for shared PostgreSQL repositories."""

from hope_job_agent.persistence.company_repository import CompanyRepository
from hope_job_agent.persistence.dedup import (
    canonicalize_job_url,
    canonicalize_url,
    compute_canonical_fingerprint,
    compute_content_hash,
    job_identity_keys,
    normalize_company_name,
    normalize_location,
    normalize_title,
    normalize_url,
    source_external_identity,
    url_identity,
)
from hope_job_agent.persistence.embedding_repository import EmbeddingRepository
from hope_job_agent.persistence.job_repository import (
    JobPostingRepository,
    UpsertSummary,
)
from hope_job_agent.persistence.source_run_repository import SourceRunRepository

__all__ = [
    "CompanyRepository",
    "EmbeddingRepository",
    "JobPostingRepository",
    "SourceRunRepository",
    "UpsertSummary",
    "canonicalize_job_url",
    "canonicalize_url",
    "compute_canonical_fingerprint",
    "compute_content_hash",
    "job_identity_keys",
    "normalize_company_name",
    "normalize_location",
    "normalize_title",
    "normalize_url",
    "source_external_identity",
    "url_identity",
]

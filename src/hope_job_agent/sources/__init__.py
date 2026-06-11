"""Approved-source adapter interfaces and placeholders."""

from hope_job_agent.sources.approved_json import (
    ApprovedJsonJobSource,
    ApprovedJsonSourceError,
)
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.employer_careers import EmployerCareersSource
from hope_job_agent.sources.handshake import HandshakeSource
from hope_job_agent.sources.ksbit_export import (
    KsbitExportSource,
    KsbitExportSourceError,
)
from hope_job_agent.sources.linkedin_reference import LinkedInReferenceSource
from hope_job_agent.sources.registry import (
    SOURCE_REGISTRY,
    SourceComplianceError,
    SourceMetadata,
    SourceStatus,
    ensure_source_allowed,
    get_source_metadata,
)

__all__ = [
    "ApprovedJsonJobSource",
    "ApprovedJsonSourceError",
    "BaseJobSource",
    "EmployerCareersSource",
    "HandshakeSource",
    "KsbitExportSource",
    "KsbitExportSourceError",
    "LinkedInReferenceSource",
    "SOURCE_REGISTRY",
    "SourceComplianceError",
    "SourceMetadata",
    "SourceStatus",
    "ensure_source_allowed",
    "get_source_metadata",
]

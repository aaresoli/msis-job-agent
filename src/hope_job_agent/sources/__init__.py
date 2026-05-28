"""Approved-source adapter interfaces and placeholders."""

from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.employer_careers import EmployerCareersSource
from hope_job_agent.sources.handshake import HandshakeSource
from hope_job_agent.sources.linkedin_reference import LinkedInReferenceSource

__all__ = [
    "BaseJobSource",
    "EmployerCareersSource",
    "HandshakeSource",
    "LinkedInReferenceSource",
]

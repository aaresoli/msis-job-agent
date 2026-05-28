"""Placeholder for future official Handshake access."""

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


class HandshakeSource(BaseJobSource):
    """Handshake adapter stub.

    Official access/API approval is required before implementation.
    """

    source_name = "handshake"

    def fetch_jobs(self) -> list[JobPosting]:
        """Block use until official Handshake access is approved."""

        raise NotImplementedError(
            "Handshake official access/API approval is required before implementation."
        )

    def health_check(self) -> bool:
        """Return False until approved access is configured."""

        return False

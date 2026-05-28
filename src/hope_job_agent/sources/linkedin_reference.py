"""Placeholder for approved and compliant LinkedIn reference workflows."""

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


class LinkedInReferenceSource(BaseJobSource):
    """LinkedIn reference adapter stub.

    LinkedIn access must use approved and compliant methods only. Do not add
    LinkedIn scraping or login automation here.
    """

    source_name = "linkedin_reference"

    def fetch_jobs(self) -> list[JobPosting]:
        """Block use until a compliant LinkedIn access method is approved."""

        raise NotImplementedError(
            "LinkedIn access must use approved/compliant methods only."
        )

    def health_check(self) -> bool:
        """Return False until approved access is configured."""

        return False

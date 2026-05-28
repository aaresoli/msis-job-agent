"""Base interface for approved job source adapters."""

from abc import ABC, abstractmethod

from hope_job_agent.models.job import JobPosting


class BaseJobSource(ABC):
    """Abstract adapter for a job source.

    Implementations must be approved before they connect to a live source.
    Do not add scraping, login automation, CAPTCHA bypassing, proxy rotation, or
    restricted-source collection in subclasses.
    """

    source_name: str

    @abstractmethod
    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch jobs from an approved source."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return whether the source adapter is ready to use."""

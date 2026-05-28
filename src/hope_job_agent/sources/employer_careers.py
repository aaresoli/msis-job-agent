"""Placeholder adapter for approved employer career pages."""

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


class EmployerCareersSource(BaseJobSource):
    """Mock employer careers source.

    A real implementation must be approved for each employer source before any
    live collection is added.
    """

    source_name = "employer_careers"

    def fetch_jobs(self) -> list[JobPosting]:
        """Return mock jobs so the pipeline can be tested without live access."""

        return [
            JobPosting(
                source=self.source_name,
                title="Data Analyst Intern",
                company="Example Employer",
                location="Bloomington, IN",
                description="Analyze business data with SQL, Python, and dashboards.",
                url="https://example.com/careers/data-analyst-intern",
                concentration_tags=["Business Analytics"],
                opt_cpt_flag=True,
            )
        ]

    def health_check(self) -> bool:
        """The mock adapter is always available."""

        return True

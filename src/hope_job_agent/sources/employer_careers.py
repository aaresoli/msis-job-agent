"""Temporary Sprint 2 prototype for approved employer-career data."""

from datetime import date

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


class EmployerCareersSource(BaseJobSource):
    """Return local sample data that represents a second approved source.

    This Sprint 2 prototype performs no live collection or external requests.
    It can later be replaced by approved Greenhouse, Lever, or KelleyLink
    adapters while preserving the shared ``BaseJobSource`` contract.
    """

    source_name = "employer_careers"

    def fetch_jobs(self) -> list[JobPosting]:
        """Return one sample posting for each MSIS concentration track."""

        return [
            JobPosting(
                source=self.source_name,
                title="Data Analyst Intern",
                company="Northstar Retail Group",
                location="Indianapolis, IN",
                description=(
                    "Analyze customer and operations data using SQL, Python, "
                    "and business intelligence dashboards."
                ),
                url="https://careers.example.com/northstar/data-analyst-intern",
                posted_date=date(2026, 6, 1),
                concentration_tags=["Business Analytics"],
                opt_cpt_flag=True,
            ),
            JobPosting(
                source=self.source_name,
                title="Cybersecurity Risk Intern",
                company="Summit Financial Services",
                location="Chicago, IL",
                description=(
                    "Support security risk assessments, control testing, and "
                    "vulnerability reporting."
                ),
                url="https://careers.example.com/summit/cybersecurity-risk-intern",
                posted_date=date(2026, 5, 29),
                concentration_tags=["Cybersecurity"],
                opt_cpt_flag=True,
            ),
            JobPosting(
                source=self.source_name,
                title="Digital Transformation Analyst Intern",
                company="Horizon Logistics",
                location="Louisville, KY",
                description=(
                    "Evaluate digital workflows, automation opportunities, and "
                    "cloud tools that improve customer and employee experiences."
                ),
                url=(
                    "https://careers.example.com/horizon/"
                    "digital-transformation-analyst-intern"
                ),
                posted_date=date(2026, 5, 28),
                concentration_tags=["Digital Enterprise Systems"],
                opt_cpt_flag=True,
            ),
            JobPosting(
                source=self.source_name,
                title="Enterprise Systems Analyst",
                company="Lakeshore Manufacturing",
                location="Columbus, IN",
                description=(
                    "Improve ERP workflows, reporting, and integrations for "
                    "operations teams."
                ),
                url="https://careers.example.com/lakeshore/enterprise-systems-analyst",
                posted_date=date(2026, 5, 27),
                concentration_tags=["Enterprise Systems"],
                opt_cpt_flag=None,
            ),
            JobPosting(
                source=self.source_name,
                title="Technology Strategy Consulting Intern",
                company="Beacon Advisory Partners",
                location="Chicago, IL",
                description=(
                    "Research technology investments, assess operating models, "
                    "and prepare recommendations for client transformation programs."
                ),
                url=(
                    "https://careers.example.com/beacon/"
                    "technology-strategy-consulting-intern"
                ),
                posted_date=date(2026, 5, 25),
                concentration_tags=["IT Strategy / Consulting"],
                opt_cpt_flag=True,
            ),
        ]

    def health_check(self) -> bool:
        """Return True because the local Sprint 2 sample data is always available."""

        return True

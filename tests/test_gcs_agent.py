from datetime import date

from hope_job_agent.agents.gcs_agent import summarize_jobs_for_gcs
from hope_job_agent.models.job import JobPosting


def test_gcs_summary_includes_program_level_trend_fields():
    jobs = [
        JobPosting(
            source="employer_careers",
            title="Data Analyst Intern",
            company="Example Analytics",
            location="Indianapolis, IN",
            description="Use SQL dashboards.",
            url="https://example.com/jobs/data-analyst",
            posted_date=date(2026, 6, 3),
            seniority="Entry",
            concentration_tags=["Data Analytics and AI"],
            role_tags=["Data Analyst / BI Engineer"],
            opt_cpt_flag=True,
        )
    ]

    summary = summarize_jobs_for_gcs(jobs)

    assert summary["total_jobs"] == 1
    assert summary["companies"] == {"Example Analytics": 1}
    assert summary["roles"] == {"Data Analyst / BI Engineer": 1}
    assert summary["concentrations"] == {"Data Analytics and AI": 1}
    assert summary["opt_cpt_signals"] == {"cpt_opt_friendly": 1}
    assert summary["posting_weeks"] == {"2026-06-01": 1}

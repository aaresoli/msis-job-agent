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


def test_gcs_summary_includes_enriched_dashboard_contract():
    jobs = [
        JobPosting(
            source="employer_careers",
            title="Data Analyst Intern",
            company="Example Analytics",
            location="Indianapolis, IN",
            description="Use SQL dashboards.",
            url="https://example.com/jobs/data-analyst",
            posted_date=date(2026, 6, 20),
            seniority="Entry",
            employment_type="Internship",
            concentration_tags=["Data Analytics and AI"],
            role_tags=["Data Analyst / BI Engineer"],
            opt_cpt_flag=True,
        ),
        JobPosting(
            source="employer_careers",
            title="Cybersecurity Analyst Intern",
            company="Secure Corp",
            location="Chicago, IL",
            description="Investigate SIEM alerts.",
            url="https://example.com/jobs/cyber",
            posted_date=date(2026, 1, 1),
            seniority="Entry",
            employment_type="Internship",
            concentration_tags=["Cybersecurity and Risk Analytics"],
            role_tags=["Cybersecurity Analyst"],
            opt_cpt_flag=None,
        ),
    ]

    summary = summarize_jobs_for_gcs(jobs, today=date(2026, 6, 30))

    assert summary["concentration_codes"]["Data Analytics and AI"] == "DA & AI"
    assert summary["employment_types"] == {"Internship": 2}
    assert summary["top_employers"][0]["count"] == 1
    assert summary["roles_by_concentration"]["Data Analytics and AI"] == {
        "Data Analyst / BI Engineer": 1
    }
    assert summary["opt_cpt_by_concentration"]["Cybersecurity and Risk Analytics"] == {
        "unknown": 1
    }
    assert summary["recency"]["last_30_days"] == 1
    assert summary["recency"]["last_90_days"] == 1

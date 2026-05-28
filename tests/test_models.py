from hope_job_agent.models.job import JobPosting


def test_job_posting_model_creation():
    job = JobPosting(
        source="employer_careers",
        title="Business Analyst Intern",
        company="Example Employer",
        location="Indianapolis, IN",
        description="Use SQL and analytics to support consulting projects.",
        url="https://example.com/jobs/business-analyst-intern",
        concentration_tags=["Business Analytics"],
        opt_cpt_flag=True,
    )

    assert job.title == "Business Analyst Intern"
    assert job.company == "Example Employer"
    assert job.concentration_tags == ["Business Analytics"]
    assert job.opt_cpt_flag is True

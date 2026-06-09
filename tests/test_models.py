import pytest
from pydantic import ValidationError

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile


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
    assert job.employment_type is None
    assert job.raw_metadata == {}
    assert job.created_at is not None


def test_job_posting_requires_core_fields():
    with pytest.raises(ValidationError):
        JobPosting(
            source="employer_careers",
            title=" ",
            company="Example Employer",
            location="Indianapolis, IN",
            description="Use SQL.",
            url="https://example.com/jobs/bad",
        )


def test_student_profile_supports_v1_fields_and_stage_alias():
    profile = StudentProfile(
        name="Fixture Student",
        concentration="Data Analytics and AI",
        academic_stage="Incoming student (Fall)",
        target_roles=["Data Analyst / BI Engineer"],
        skills=["SQL"],
        work_auth_status="Need CPT / OPT sponsorship",
        geo_preference=["Midwest (Chicago, Indy, Cincy)"],
        delivery_preference="Dashboard / spreadsheet view",
    )

    assert profile.stage == "Incoming student (Fall)"
    assert profile.needs_cpt_opt is True

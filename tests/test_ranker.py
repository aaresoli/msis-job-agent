from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.scoring.ranker import rank_jobs_for_student, score_job_for_student


def test_ranking_gives_higher_score_to_more_relevant_jobs():
    student = StudentProfile(
        name="Test Student",
        concentration="Business Analytics",
        target_roles=["data analyst"],
        skills=["SQL", "Python"],
        stage="internship search",
    )
    relevant_job = JobPosting(
        source="employer_careers",
        title="Data Analyst Intern",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Work with SQL, Python, dashboards, and business data.",
        url="https://example.com/jobs/data-analyst",
        concentration_tags=["Business Analytics"],
    )
    less_relevant_job = JobPosting(
        source="employer_careers",
        title="Help Desk Assistant",
        company="Example Support",
        location="Bloomington, IN",
        description="Support internal users and document tickets.",
        url="https://example.com/jobs/help-desk",
        concentration_tags=["Enterprise Systems"],
    )

    assert score_job_for_student(student, relevant_job) > score_job_for_student(
        student, less_relevant_job
    )

    ranked = rank_jobs_for_student(student, [less_relevant_job, relevant_job])

    assert ranked[0].job.title == "Data Analyst Intern"

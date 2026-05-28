"""Placeholder student-facing matching agent."""

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.scoring.ranker import rank_jobs_for_student


def get_student_matches(
    student_profile: StudentProfile, jobs: list[JobPosting]
) -> list[JobMatch]:
    """Return ranked job matches for a student profile."""

    return rank_jobs_for_student(student_profile, jobs)

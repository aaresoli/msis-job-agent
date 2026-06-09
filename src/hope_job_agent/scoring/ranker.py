"""Deterministic ranking helpers for student-job matching."""

import re

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile


def _normalize_terms(values: list[str]) -> list[str]:
    """Lowercase and trim profile terms for consistent scoring."""

    return [value.strip().lower() for value in values if value.strip()]


def _contains_term(text: str, term: str) -> bool:
    """Return whether a term appears as words in the searchable text."""

    pattern = rf"\b{re.escape(term)}\b"
    return re.search(pattern, text) is not None


def score_job_for_student(student: StudentProfile, job: JobPosting) -> float:
    """Score a job based on skills, target roles, concentration overlap, and position seniority"""

    searchable_text = f"{job.title} {job.description}".lower()
    senior_def = ["manager", "director", "lead", "principal", "executive", "head", "expert"]
    mid_def = ["senior", "experienced", "proficient", "seasoned"]
    early_mid_def = ["intern", "new grad", "entry", "junior", "rotational", "novice"]
    entry_def = ["internship", "graduate", "trainee"]
    seniority_score = 0.0
    seniority_label = ""
    score = 0.0

    for skill in _normalize_terms(student.skills):
        if _contains_term(searchable_text, skill):
            score += 2.0

    for role in _normalize_terms(student.target_roles):
        if _contains_term(searchable_text, role):
            score += 3.0

    if student.concentration in job.concentration_tags:
        score += 1.0

    for term in searchable_text:
        if _contains_term(senior_def, term) == True:
            seniority_score += 2.0
        if _contains_term(mid_def, term) == True:
            seniority_score += 1.0
        if _contains_term(early_mid_def, term) == True:
            seniority_score -= 1.0
        if _contains_term(entry_def, term) == True:
            seniority_score -= 2.0
        
    if seniority_score >=2:
        seniority_label = "Senior"
    elif seniority_score == 1:
        seniority_label = "Mid"
    elif seniority_score == 0:
        seniority_label = "Early/Mid"
    elif seniority_score <= -1:
        seniority_label = "Entry"
        
    return score, seniority_label


def rank_jobs_for_student(
    student: StudentProfile, jobs: list[JobPosting]
) -> list[JobMatch]:
    """Return jobs sorted from highest to lowest deterministic relevance score."""

    matches = [
        JobMatch(job=job, score=score_job_for_student(student, job)) for job in jobs
    ]
    return sorted(
        matches,
        key=lambda match: (
            match.score[0],
            match.score[1],
            match.job.posted_date is not None,
            match.job.posted_date,
            match.job.company,
            match.job.title,
        ),
        reverse=True,
    )

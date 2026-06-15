"""Deterministic ranking helpers for student-job matching."""

import re
from dataclasses import dataclass

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile


@dataclass(frozen=True)
class RankingWeights:
    """Documented v0 ranking rubric weights."""

    skill_match: float = 2.0
    target_role_match: float = 3.0
    concentration_match: float = 2.0
    opt_cpt_match: float = 1.0
    seniority_match: float = 1.0
    seniority_mismatch_penalty: float = -1.0


DEFAULT_RANKING_WEIGHTS = RankingWeights()


def _normalize_terms(values: list[str]) -> list[str]:
    """Lowercase and trim profile terms for consistent scoring."""

    return [value.strip().lower() for value in values if value.strip()]


def _contains_term(text: str, term: str) -> bool:
    """Return whether a term appears as words in the searchable text."""

    pattern = rf"\b{re.escape(term)}\b"
    return re.search(pattern, text) is not None


def score_job_for_student(
    student: StudentProfile,
    job: JobPosting,
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
) -> float:
    """Score a job based on skills, target roles, and concentration overlap."""

    score, _reasons, _metadata = explain_job_score(student, job, weights)
    return score


def explain_job_score(
    student: StudentProfile,
    job: JobPosting,
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
) -> tuple[float, list[str], dict[str, str]]:
    """Return an explainable score tuple for one student-job pair."""

    searchable_text = f"{job.title} {job.description}".lower()
    score = 0.0
    individual_scores = {"Skill Score": 0.0, "Role Score": 0.0, "Concentration Score": 0.0, "OPT/CPT Score": 0.0, "Seniority Match Score": 0.0, "Seniority Mismatch Score": 0.0}
    reasons: list[str] = []

    for skill in _normalize_terms(student.skills):
        if _contains_term(searchable_text, skill):
            score += weights.skill_match
            individual_scores["Skill Score"] += weights.skill_match
            reasons.append(f"Skill match: {skill}")

    for role in _normalize_terms(student.target_roles):
        if _contains_term(searchable_text, role) or role in [
            tag.casefold() for tag in job.role_tags
        ]:
            score += weights.target_role_match
            individual_scores["Role Score"] += weights.target_role_match
            reasons.append(f"Target role match: {role}")

    if student.concentration in job.concentration_tags:
        score += weights.concentration_match
        individual_scores["Concentration Score"] += weights.concentration_match
        reasons.append(f"Concentration match: {student.concentration}")

    if student.needs_cpt_opt and job.opt_cpt_flag is True:
        score += weights.opt_cpt_match
        individual_scores["OPT/CPT Score"] += weights.opt_cpt_match
        reasons.append("CPT/OPT-friendly signal")

    seniority_label = job.seniority or infer_seniority(job)
    preferred_seniority = _preferred_seniority(student)
    if preferred_seniority and seniority_label == preferred_seniority:
        score += weights.seniority_match
        individual_scores["Seniority Match Score"] += weights.seniority_match
        reasons.append(f"Seniority match: {seniority_label}")
    elif preferred_seniority and seniority_label:
        score += weights.seniority_mismatch_penalty
        individual_scores["Seniority Mismatch Score"] += weights.seniority_mismatch_penalty
        reasons.append(f"Seniority mismatch: {seniority_label}")

    return score, reasons, {"seniority": seniority_label}


def infer_seniority(job: JobPosting) -> str:
    """Infer a coarse seniority label from the title and description."""

    searchable_text = f"{job.title} {job.description}".lower()
    senior_terms = ["manager", "director", "lead", "principal", "executive", "head"]
    mid_terms = ["senior", "experienced"]
    entry_terms = ["intern", "internship", "new grad", "entry", "junior", "rotational"]

    if any(_contains_term(searchable_text, term) for term in senior_terms):
        return "Senior"
    if any(_contains_term(searchable_text, term) for term in mid_terms):
        return "Mid"
    if any(_contains_term(searchable_text, term) for term in entry_terms):
        return "Entry"
    return "Early/Mid"


def _preferred_seniority(student: StudentProfile) -> str | None:
    stage = (student.academic_stage or student.stage or "").casefold()
    if any(term in stage for term in ["incoming", "internship", "fall"]):
        return "Entry"
    if any(term in stage for term in ["returning", "finishing", "graduate"]):
        return "Early/Mid"
    return None


def rank_jobs_for_student(
    student: StudentProfile,
    jobs: list[JobPosting],
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
) -> list[JobMatch]:
    """Return jobs sorted from highest to lowest deterministic relevance score."""

    matches = []
    for job in jobs:
        score, reasons, metadata = explain_job_score(student, job, weights)
        matches.append(
            JobMatch(job=job, score=score, reasons=reasons, metadata=metadata)
        )

    return sorted(
        matches,
        key=lambda match: (
            match.score,
            match.job.posted_date is not None,
            match.job.posted_date,
            match.job.company,
            match.job.title,
        ),
        reverse=True,
    )

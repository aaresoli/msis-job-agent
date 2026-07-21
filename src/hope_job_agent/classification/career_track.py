"""Deterministic internship vs full-time career-track classification.

The student dashboard splits postings into an "Internship track" and a
"Full-time track". This module derives that binary track from signals that the
sources already provide (employment type, experience level, career stage) plus
title keywords, using only rule logic -- no LLM calls.
"""

from __future__ import annotations

import re

from hope_job_agent.models.job import JobPosting

CAREER_TRACK_INTERNSHIP = "internship"
CAREER_TRACK_FULL_TIME = "full_time"
CAREER_TRACK_UNKNOWN = "unknown"

CAREER_TRACKS = [
    CAREER_TRACK_INTERNSHIP,
    CAREER_TRACK_FULL_TIME,
    CAREER_TRACK_UNKNOWN,
]

_INTERNSHIP_TITLE_KEYWORDS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "summer analyst",
    "summer associate",
]

_FULL_TIME_TITLE_KEYWORDS = [
    "new grad",
    "new graduate",
    "university graduate",
    "entry level",
    "entry-level",
    "early career",
    "early-career",
    "rotational program",
]

_INTERNSHIP_EMPLOYMENT_TYPES = {"internship", "intern", "co-op", "coop"}


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def _contains(text: str, keyword: str) -> bool:
    """Word-boundary-aware substring match (handles multi-word phrases)."""

    escaped = re.escape(keyword.casefold().strip())
    if not escaped:
        return False
    return re.search(rf"(?<!\w){escaped}(?!\w)", text) is not None


def _matches_any(text: str, keywords: list[str]) -> bool:
    return any(_contains(text, keyword) for keyword in keywords)


def infer_career_track(job: JobPosting) -> str:
    """Classify a posting as internship, full_time, or unknown.

    Signals are checked in priority order so an explicit internship marker in
    the title or employment type always wins over a generic "Full-time"
    contract type (LinkedIn frequently labels internships as full-time).
    """

    title = _norm(job.title)
    employment_type = _norm(job.employment_type)
    seniority = _norm(job.seniority)
    career_stage = _norm(job.career_stage)

    if _matches_any(title, _INTERNSHIP_TITLE_KEYWORDS):
        return CAREER_TRACK_INTERNSHIP
    # A senior-stage title vetoes the employment-type internship label, which
    # sources sometimes misapply (e.g. "Staff Engineer" tagged Internship).
    if employment_type in _INTERNSHIP_EMPLOYMENT_TYPES and career_stage != "senior":
        return CAREER_TRACK_INTERNSHIP
    if seniority == "internship":
        return CAREER_TRACK_INTERNSHIP
    # Explicit full-time title markers ("New Grad", "Entry Level") outrank the
    # career-stage heuristic, which is derived from fuzzier description text.
    if _matches_any(title, _FULL_TIME_TITLE_KEYWORDS):
        return CAREER_TRACK_FULL_TIME
    if career_stage == "internship":
        return CAREER_TRACK_INTERNSHIP

    if employment_type.startswith("full"):
        return CAREER_TRACK_FULL_TIME

    return CAREER_TRACK_UNKNOWN

"""Unit tests for the deterministic career-track classifier."""

import pytest

from hope_job_agent.classification.career_track import (
    CAREER_TRACK_FULL_TIME,
    CAREER_TRACK_INTERNSHIP,
    CAREER_TRACK_UNKNOWN,
    infer_career_track,
)
from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.models.job import JobPosting


def _make_job(**overrides: object) -> JobPosting:
    payload: dict[str, object] = {
        "source": "approved_json",
        "title": "Business Systems Analyst",
        "company": "Acme Analytics",
        "location": "Indianapolis, IN",
        "description": "Work with SQL, Tableau, and stakeholders.",
        "url": "https://example.com/jobs/1",
    }
    payload.update(overrides)
    return JobPosting(**payload)


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    [
        "Data Analyst Intern",
        "Software Engineering Internship",
        "Technology Co-op",
        "Cybersecurity Coop - Summer",
        "Summer Analyst, Technology Risk",
        "Summer Associate - Digital Consulting",
    ],
)
def test_internship_from_title(title: str) -> None:
    assert infer_career_track(_make_job(title=title)) == CAREER_TRACK_INTERNSHIP


@pytest.mark.unit
def test_internship_title_beats_full_time_employment_type() -> None:
    job = _make_job(title="Data Analyst Intern", employment_type="Full-time")
    assert infer_career_track(job) == CAREER_TRACK_INTERNSHIP


@pytest.mark.unit
def test_internship_from_employment_type() -> None:
    job = _make_job(employment_type="Internship")
    assert infer_career_track(job) == CAREER_TRACK_INTERNSHIP


@pytest.mark.unit
def test_internship_from_seniority() -> None:
    job = _make_job(seniority="Internship")
    assert infer_career_track(job) == CAREER_TRACK_INTERNSHIP


@pytest.mark.unit
def test_internship_from_career_stage() -> None:
    job = _make_job(career_stage="internship")
    assert infer_career_track(job) == CAREER_TRACK_INTERNSHIP


@pytest.mark.unit
def test_internal_auditor_is_not_an_internship() -> None:
    job = _make_job(title="Internal Auditor", employment_type="Full-time")
    assert infer_career_track(job) == CAREER_TRACK_FULL_TIME


@pytest.mark.unit
@pytest.mark.parametrize("employment_type", ["Full-time", "Full Time", "FULL-TIME"])
def test_full_time_from_employment_type(employment_type: str) -> None:
    job = _make_job(employment_type=employment_type)
    assert infer_career_track(job) == CAREER_TRACK_FULL_TIME


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    [
        "New Grad Software Engineer",
        "Entry Level Systems Analyst",
        "Early Career Data Analyst",
        "Technology Rotational Program Associate",
    ],
)
def test_full_time_from_title_keywords(title: str) -> None:
    assert infer_career_track(_make_job(title=title)) == CAREER_TRACK_FULL_TIME


@pytest.mark.unit
def test_unknown_when_no_signal() -> None:
    assert infer_career_track(_make_job()) == CAREER_TRACK_UNKNOWN


@pytest.mark.unit
def test_classifier_stamps_career_track() -> None:
    classified = classify_job_posting(
        _make_job(title="Data Analyst Intern", employment_type="Internship")
    )
    assert classified.career_track == CAREER_TRACK_INTERNSHIP

    classified_full_time = classify_job_posting(_make_job(employment_type="Full-time"))
    assert classified_full_time.career_track == CAREER_TRACK_FULL_TIME

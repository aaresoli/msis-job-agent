import json
from pathlib import Path

from hope_job_agent.classification.taxonomy import (
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
)

DATASET_PATH = Path("data/gold_job_postings_labeled.json")

ROLE_FITS = {"strong", "moderate", "weak", "not_fit"}
CONCENTRATION_FITS = {"strong", "moderate", "weak", "not_fit"}
SENIORITY_LEVELS = {"internship", "entry_level", "mid_level", "senior_level"}
RELEVANCE_LEVELS = {"high", "medium", "low"}


def test_gold_job_postings_dataset_is_valid():
    postings = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    assert len(postings) >= 10
    assert {posting["id"] for posting in postings} == {
        f"gold-{index:03d}" for index in range(1, len(postings) + 1)
    }

    for posting in postings:
        assert posting["source"]
        assert posting["source_url"].startswith("https://")
        assert posting["retrieved_date"] == "2026-06-09"
        assert posting["title"]
        assert posting["company"]
        assert posting["location"]
        assert posting["posting_summary"]
        assert posting["annotator_notes"]

        labels = posting["manual_labels"]
        assert labels["primary_role"] in MSIS_TARGET_ROLES
        assert labels["role_fit"] in ROLE_FITS
        assert labels["concentration"] in MSIS_CONCENTRATIONS
        assert labels["concentration_fit"] in CONCENTRATION_FITS
        assert labels["seniority"] in SENIORITY_LEVELS
        assert labels["relevance"] in RELEVANCE_LEVELS


def test_gold_job_postings_cover_core_msis_labels():
    postings = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    labels = [posting["manual_labels"] for posting in postings]

    assert {label["primary_role"] for label in labels} >= {
        "IT Consultant / Tech Risk",
        "Data Analyst / BI Engineer",
        "Cybersecurity Analyst",
        "Product / Project Manager",
        "Software Engineer",
        "Other",
    }
    assert {label["concentration"] for label in labels} == set(MSIS_CONCENTRATIONS)
    assert {label["relevance"] for label in labels} >= {"high", "medium", "low"}
    assert {label["seniority"] for label in labels} >= {"internship", "mid_level"}

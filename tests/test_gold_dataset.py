from hope_job_agent.classification.taxonomy import MSIS_CONCENTRATIONS
from hope_job_agent.datasets.gold_postings import (
    DATASET_PATH,
    GoldJobPosting,
    load_gold_postings,
    validate_gold_posting_taxonomy,
)

ROLE_FITS = {"strong", "moderate", "weak", "not_fit"}
CONCENTRATION_FITS = {"strong", "moderate", "weak", "not_fit"}
SENIORITY_LEVELS = {"internship", "entry_level", "mid_level", "senior_level"}
RELEVANCE_LEVELS = {"high", "medium", "low"}


def test_gold_job_postings_dataset_is_valid():
    postings = load_gold_postings(DATASET_PATH)

    assert len(postings) >= 10
    assert {posting.id for posting in postings} == {
        f"gold-{index:03d}" for index in range(1, len(postings) + 1)
    }
    assert len({str(posting.source_url) for posting in postings}) == len(postings)

    for posting in postings:
        assert isinstance(posting, GoldJobPosting)
        assert posting.source
        assert str(posting.source_url).startswith("https://")
        assert posting.retrieved_date.isoformat() == "2026-06-09"
        assert posting.title
        assert posting.company
        assert posting.location
        assert posting.posting_summary
        assert posting.annotator_notes

        labels = posting.manual_labels
        assert labels.role_fit in ROLE_FITS
        assert labels.concentration_fit in CONCENTRATION_FITS
        assert labels.seniority in SENIORITY_LEVELS
        assert labels.relevance in RELEVANCE_LEVELS

    validate_gold_posting_taxonomy(postings)


def test_gold_job_postings_cover_core_msis_labels():
    postings = load_gold_postings(DATASET_PATH)
    labels = [posting.manual_labels for posting in postings]

    assert {label.primary_role for label in labels} >= {
        "IT Consultant / Tech Risk",
        "Data Analyst / BI Engineer",
        "Cybersecurity Analyst",
        "Product / Project Manager",
        "Software Engineer",
        "Other",
    }
    gold_concentrations = {label.concentration for label in labels}
    # Every gold label must be a valid official concentration.
    assert gold_concentrations <= set(MSIS_CONCENTRATIONS)
    # The four established tracks have real labeled postings. "Digital Platforms
    # and Security" is newly added and has no real public gold example yet;
    # fabricating one would undermine the "real postings" gold set.
    assert gold_concentrations >= {
        "Data Analytics and AI",
        "Cybersecurity and Risk Analytics",
        "Digital Enterprise Systems and AI",
        "IS Research",
    }
    assert {label.role_fit for label in labels} >= {"strong", "moderate", "weak"}
    assert {label.concentration_fit for label in labels} >= {
        "strong",
        "weak",
    }
    assert {label.relevance for label in labels} >= {"high", "medium", "low"}
    assert {label.seniority for label in labels} >= {"internship", "mid_level"}


def test_gold_job_postings_are_convertible_to_normalized_jobs():
    jobs = [posting.to_job_posting() for posting in load_gold_postings(DATASET_PATH)]

    assert all(job.description for job in jobs)
    assert all(job.url.startswith("https://") for job in jobs)
    assert any(job.role_tags == ["Other"] for job in jobs)

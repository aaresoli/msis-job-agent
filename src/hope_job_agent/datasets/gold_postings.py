"""Typed loader for the manually labeled gold job posting dataset."""

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from hope_job_agent.classification.taxonomy import (
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
)
from hope_job_agent.models.job import JobPosting

DATASET_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "gold_job_postings_labeled.json"
)

RoleFit = Literal["strong", "moderate", "weak", "not_fit"]
ConcentrationFit = Literal["strong", "moderate", "weak", "not_fit"]
SeniorityLevel = Literal["internship", "entry_level", "mid_level", "senior_level"]
RelevanceLevel = Literal["high", "medium", "low"]


class GoldPostingLabels(BaseModel):
    """Manual labels assigned by reviewers for classifier and ranker evaluation."""

    primary_role: str
    role_fit: RoleFit
    concentration: str
    concentration_fit: ConcentrationFit
    seniority: SeniorityLevel
    relevance: RelevanceLevel


class GoldJobPosting(BaseModel):
    """A real job posting record with manual MSIS relevance labels."""

    id: str
    source: str
    source_url: HttpUrl
    retrieved_date: date
    title: str
    company: str
    location: str
    posting_summary: str = Field(min_length=40)
    manual_labels: GoldPostingLabels
    annotator_notes: str = Field(min_length=40)

    def to_job_posting(self) -> JobPosting:
        """Convert the labeled record into the normalized job model."""

        return JobPosting(
            source=self.source,
            title=self.title,
            company=self.company,
            location=self.location,
            description=self.posting_summary,
            url=str(self.source_url),
            posted_date=None,
            concentration_tags=[self.manual_labels.concentration],
            role_tags=[self.manual_labels.primary_role],
        )


def load_gold_postings(path: Path = DATASET_PATH) -> list[GoldJobPosting]:
    """Load and validate the manually labeled gold job postings."""

    return [
        GoldJobPosting.model_validate(posting)
        for posting in json.loads(path.read_text(encoding="utf-8"))
    ]


def validate_gold_posting_taxonomy(postings: list[GoldJobPosting]) -> None:
    """Raise ValueError if manual labels drift from the supported taxonomy."""

    valid_roles = set(MSIS_TARGET_ROLES)
    valid_concentrations = set(MSIS_CONCENTRATIONS)
    invalid_roles = sorted(
        {
            posting.manual_labels.primary_role
            for posting in postings
            if posting.manual_labels.primary_role not in valid_roles
        }
    )
    invalid_concentrations = sorted(
        {
            posting.manual_labels.concentration
            for posting in postings
            if posting.manual_labels.concentration not in valid_concentrations
        }
    )

    if invalid_roles or invalid_concentrations:
        details = []
        if invalid_roles:
            details.append(f"roles={invalid_roles}")
        if invalid_concentrations:
            details.append(f"concentrations={invalid_concentrations}")
        raise ValueError(
            "Gold dataset labels are outside the taxonomy: " + ", ".join(details)
        )

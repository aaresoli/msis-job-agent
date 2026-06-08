"""Rule-based v0 classifier for MSIS role and concentration tags."""

import re
from dataclasses import dataclass

from hope_job_agent.classification.taxonomy import (
    CONCENTRATION_KEYWORDS,
    LEGACY_CONCENTRATION_ALIASES,
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
    ROLE_KEYWORDS,
    ROLE_TO_CONCENTRATIONS,
)
from hope_job_agent.models.job import JobPosting


@dataclass(frozen=True)
class JobClassification:
    """MSIS tags inferred for a job posting."""

    role_tags: list[str]
    concentration_tags: list[str]


def classify_job(job: JobPosting) -> JobClassification:
    """Classify a posting by MSIS target role and concentration track.

    This first version is intentionally deterministic. It combines explicit
    source-provided tags with keyword rules over the posting title and
    description, then maps matched roles into the concentration tracks used by
    the student profile schema.
    """

    searchable_text = _normalize_text(
        " ".join([job.title, job.company, job.location, job.description])
    )
    role_tags = _dedupe(
        [
            *[tag for tag in job.role_tags if tag in MSIS_TARGET_ROLES],
            *_match_keywords(searchable_text, ROLE_KEYWORDS),
        ]
    )
    concentration_tags = _dedupe(
        [
            *_normalize_existing_concentrations(job.concentration_tags),
            *_concentrations_for_roles(role_tags),
            *_match_keywords(searchable_text, CONCENTRATION_KEYWORDS),
        ]
    )

    return JobClassification(
        role_tags=role_tags,
        concentration_tags=concentration_tags,
    )


def classify_job_posting(job: JobPosting) -> JobPosting:
    """Return a copy of the posting with inferred role and concentration tags."""

    classification = classify_job(job)
    return job.model_copy(
        update={
            "role_tags": classification.role_tags,
            "concentration_tags": classification.concentration_tags,
        }
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _match_keywords(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    matches = []
    for tag, keywords in keyword_map.items():
        if any(_contains_keyword(text, keyword) for keyword in keywords):
            matches.append(tag)
    return matches


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_keyword = re.escape(keyword.casefold())
    return re.search(rf"(?<!\w){normalized_keyword}(?!\w)", text) is not None


def _normalize_existing_concentrations(tags: list[str]) -> list[str]:
    normalized = []
    for tag in tags:
        if tag in MSIS_CONCENTRATIONS:
            normalized.append(tag)
        elif tag in LEGACY_CONCENTRATION_ALIASES:
            normalized.append(LEGACY_CONCENTRATION_ALIASES[tag])
    return normalized


def _concentrations_for_roles(role_tags: list[str]) -> list[str]:
    return [
        concentration
        for role in role_tags
        for concentration in ROLE_TO_CONCENTRATIONS.get(role, [])
    ]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

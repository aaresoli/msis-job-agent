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

CLASSIFIER_VERSION = "rules-v0"
MIN_CONFIDENT_SCORE = 0.5
FALLBACK_ROLE = "Other"
FALLBACK_CONFIDENCE = 0.25


@dataclass(frozen=True)
class JobClassification:
    """MSIS tags inferred for a job posting."""

    role_tags: list[str]
    concentration_tags: list[str]
    role_confidence_scores: dict[str, float]
    concentration_confidence_scores: dict[str, float]
    is_uncertain: bool = False
    fallback_reason: str | None = None


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
    role_confidence_scores = _score_tags(
        searchable_text=searchable_text,
        title_text=_normalize_text(job.title),
        keyword_map=ROLE_KEYWORDS,
        existing_tags=[tag for tag in job.role_tags if tag in MSIS_TARGET_ROLES],
    )
    role_tags = _rank_confident_tags(role_confidence_scores, MSIS_TARGET_ROLES)
    is_uncertain = False
    fallback_reason = None

    if not role_tags:
        role_tags = [FALLBACK_ROLE]
        role_confidence_scores = {FALLBACK_ROLE: FALLBACK_CONFIDENCE}
        is_uncertain = True
        fallback_reason = "No target-role keywords or trusted source tags matched."

    concentration_confidence_scores = _score_tags(
        searchable_text=searchable_text,
        title_text=_normalize_text(job.title),
        keyword_map=CONCENTRATION_KEYWORDS,
        existing_tags=_normalize_existing_concentrations(job.concentration_tags),
    )
    concentration_confidence_scores = _merge_scores(
        concentration_confidence_scores,
        _score_concentrations_for_roles(role_confidence_scores, role_tags),
    )
    concentration_tags = _rank_confident_tags(
        concentration_confidence_scores,
        MSIS_CONCENTRATIONS,
    )

    if not concentration_tags:
        is_uncertain = True
        fallback_reason = fallback_reason or (
            "No concentration keywords, source tags, or role mappings matched."
        )

    return JobClassification(
        role_tags=role_tags,
        concentration_tags=concentration_tags,
        role_confidence_scores=role_confidence_scores,
        concentration_confidence_scores=concentration_confidence_scores,
        is_uncertain=is_uncertain,
        fallback_reason=fallback_reason,
    )


def classify_job_posting(job: JobPosting) -> JobPosting:
    """Return a copy of the posting with inferred role and concentration tags."""

    classification = classify_job(job)
    return job.model_copy(
        update={
            "role_tags": classification.role_tags,
            "concentration_tags": classification.concentration_tags,
            "role_confidence_scores": classification.role_confidence_scores,
            "concentration_confidence_scores": (
                classification.concentration_confidence_scores
            ),
            "classification_uncertain": classification.is_uncertain,
        }
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _score_tags(
    searchable_text: str,
    title_text: str,
    keyword_map: dict[str, list[str]],
    existing_tags: list[str],
) -> dict[str, float]:
    scores = {tag: 1.0 for tag in existing_tags}
    for tag, keywords in keyword_map.items():
        matched_keywords = [
            keyword
            for keyword in keywords
            if _contains_keyword(searchable_text, keyword)
        ]
        if not matched_keywords:
            continue

        title_matches = sum(
            1 for keyword in matched_keywords if _contains_keyword(title_text, keyword)
        )
        score = 0.35 + min(len(matched_keywords), 4) * 0.1 + title_matches * 0.2
        scores[tag] = max(scores.get(tag, 0.0), min(score, 0.95))

    return scores


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


def _score_concentrations_for_roles(
    role_confidence_scores: dict[str, float],
    role_tags: list[str],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for role in role_tags:
        if role == FALLBACK_ROLE:
            continue
        role_score = role_confidence_scores.get(role, 0.0)
        for concentration in ROLE_TO_CONCENTRATIONS.get(role, []):
            scores[concentration] = max(
                scores.get(concentration, 0.0),
                role_score * 0.8,
            )
    return scores


def _rank_confident_tags(
    scores: dict[str, float],
    taxonomy_order: list[str],
) -> list[str]:
    source_tags = [
        tag
        for tag, score in scores.items()
        if score == 1.0 and tag in taxonomy_order
    ]
    inferred_tags = [
        tag
        for tag in taxonomy_order
        if scores.get(tag, 0.0) >= MIN_CONFIDENT_SCORE and tag not in source_tags
    ]
    return [*source_tags, *inferred_tags]


def _merge_scores(
    first: dict[str, float],
    second: dict[str, float],
) -> dict[str, float]:
    merged = dict(first)
    for tag, score in second.items():
        merged[tag] = max(merged.get(tag, 0.0), score)
    return merged


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

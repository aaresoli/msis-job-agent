"""Rule-based work authorization detector for job postings."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from hope_job_agent.models.job import JobPosting


@dataclass(frozen=True)
class WorkAuthorizationDetection:
    """OPT/CPT and sponsorship signal inferred from a job posting."""

    opt_cpt_flag: bool | None
    matched_signals: list[str]
    requires_llm_review: bool = False
    reason: str | None = None


WorkAuthorizationLLMClassifier = Callable[
    [JobPosting, WorkAuthorizationDetection],
    bool | None,
]


FRIENDLY_PATTERNS = {
    "mentions OPT": r"\bopt\b|optional practical training",
    "mentions CPT": r"\bcpt\b|curricular practical training",
    "sponsorship available": (
        r"(visa|work authorization|employment)\s+sponsorship\s+"
        r"(is\s+)?(available|provided|offered|considered)"
    ),
    "will sponsor": r"\b(will|can|may)\s+sponsor\b",
    "F-1 friendly": r"\bf-?1\b.{0,80}\b(opt|cpt)\b",
}

RESTRICTIVE_PATTERNS = {
    "no sponsorship": r"\bno\s+(visa|employment|work authorization)?\s*sponsorship\b",
    "does not sponsor": r"\b(do|does|will)\s+not\s+sponsor\b",
    "unable to sponsor": r"\b(unable|not able)\s+to\s+sponsor\b",
    "without sponsorship": r"\bwithout\s+(current\s+or\s+future\s+)?sponsorship\b",
    "authorized without sponsorship": (
        r"authorized\s+to\s+work.{0,120}\bwithout\b.{0,80}\bsponsorship\b"
    ),
    "citizen or green card only": (
        r"\b(u\.?s\.?\s+citizen|green\s+card|permanent\s+resident)s?\s+only\b"
    ),
}

AMBIGUOUS_PATTERNS = {
    "mentions visa": r"\b(visa|h-?1b|f-?1|immigration)\b",
    "mentions sponsorship": r"\bsponsorship\b",
    "mentions work authorization": r"\b(work authorization|authorized to work)\b",
}


def detect_work_authorization(
    job: JobPosting,
    llm_classifier: WorkAuthorizationLLMClassifier | None = None,
) -> WorkAuthorizationDetection:
    """Detect OPT/CPT and sponsorship signals with deterministic rules.

    The detector intentionally leaves broad work-authorization wording as
    ambiguous so a future LLM classifier can review context-sensitive cases.
    """

    searchable_text = _normalize_text(
        " ".join([job.title, job.company, job.location, job.description])
    )
    friendly_signals = _matched_signals(searchable_text, FRIENDLY_PATTERNS)
    restrictive_signals = _matched_signals(searchable_text, RESTRICTIVE_PATTERNS)

    if friendly_signals and restrictive_signals:
        detection = WorkAuthorizationDetection(
            opt_cpt_flag=None,
            matched_signals=[*friendly_signals, *restrictive_signals],
            requires_llm_review=True,
            reason="Both sponsorship-friendly and restrictive language matched.",
        )
        return _classify_ambiguous(job, detection, llm_classifier)

    if friendly_signals:
        return WorkAuthorizationDetection(
            opt_cpt_flag=True,
            matched_signals=friendly_signals,
            reason="Posting includes CPT/OPT or sponsorship-friendly language.",
        )

    if restrictive_signals:
        return WorkAuthorizationDetection(
            opt_cpt_flag=False,
            matched_signals=restrictive_signals,
            reason="Posting includes sponsorship-restrictive language.",
        )

    ambiguous_signals = _matched_signals(searchable_text, AMBIGUOUS_PATTERNS)
    if ambiguous_signals:
        detection = WorkAuthorizationDetection(
            opt_cpt_flag=None,
            matched_signals=ambiguous_signals,
            requires_llm_review=True,
            reason="Posting mentions work authorization without a clear outcome.",
        )
        return _classify_ambiguous(job, detection, llm_classifier)

    return WorkAuthorizationDetection(
        opt_cpt_flag=None,
        matched_signals=[],
        reason="No work authorization language matched.",
    )


def _matched_signals(text: str, patterns: dict[str, str]) -> list[str]:
    return [
        label
        for label, pattern in patterns.items()
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    ]


def _classify_ambiguous(
    job: JobPosting,
    detection: WorkAuthorizationDetection,
    llm_classifier: WorkAuthorizationLLMClassifier | None,
) -> WorkAuthorizationDetection:
    if llm_classifier is None:
        return detection

    return WorkAuthorizationDetection(
        opt_cpt_flag=llm_classifier(job, detection),
        matched_signals=detection.matched_signals,
        requires_llm_review=False,
        reason="Ambiguous work authorization language classified by LLM fallback.",
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()

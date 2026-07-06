"""Transparent, deterministic MSIS relevance filtering and scoring.

This is the cheap first-pass filter that runs on every fetched posting before it
is normalized or handed to the (existing, rule-based) classifier. It uses only
keyword/rule logic -- no LLM calls -- so it is fast, free, and fully explainable.
The output ``concentration_hints`` seed the downstream classifier while the
score/matched keywords are stored on the posting for auditability.

All concentration names emitted here are the official MSIS concentration names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hope_job_agent.classification.taxonomy import MSIS_CONCENTRATIONS

DEFAULT_RELEVANCE_THRESHOLD = 3

# Positive keyword families, grouped by official MSIS concentration. Used both
# for +2 concentration-keyword scoring and to seed concentration hints so every
# official track can be represented.
CONCENTRATION_KEYWORD_FAMILIES: dict[str, list[str]] = {
    "Data Analytics and AI": [
        "data analyst",
        "business analyst",
        "bi analyst",
        "analytics engineer",
        "data engineer",
        "machine learning analyst",
        "ai analyst",
        "reporting analyst",
        "insights analyst",
        "decision science",
        "data science",
        "data scientist",
        "sql",
        "python",
        "tableau",
        "power bi",
        "looker",
        "snowflake",
        "databricks",
        "data architect",
        "ai consultant",
        "data consultant",
        "analytics",
    ],
    "Cybersecurity and Risk Analytics": [
        "cybersecurity analyst",
        "security analyst",
        "grc",
        "risk analyst",
        "iam",
        "soc",
        "cloud security",
        "threat detection",
        "privacy analyst",
        "security engineer",
        "compliance analyst",
        "incident response",
        "penetration tester",
        "ethical hacker",
        "security architect",
        "cyber risk consultant",
        "risk analytics",
    ],
    "Digital Enterprise Systems and AI": [
        "erp",
        "sap",
        "oracle",
        "salesforce",
        "workday",
        "servicenow",
        "business systems analyst",
        "enterprise applications",
        "crm",
        "scm",
        "hcm",
        "system analyst",
        "systems analyst",
        "integration specialist",
        "supply chain analyst",
        "business transformation consultant",
        "enterprise systems architect",
        "solution engineer",
        "product manager ai",
        "product manager digital platforms",
        "enterprise data management",
        "enterprise digital core",
    ],
    "Digital Platforms and Security": [
        "cloud solutions architect",
        "solutions engineer",
        "technology solutions consultant",
        "enterprise platform engineer",
        "digital solutions architect",
        "cloud infrastructure engineer",
        "enterprise systems analyst",
        "platform integration specialist",
        "cloud security engineer",
        "technical implementation consultant",
        "solution delivery analyst",
        "enterprise architect",
        "security solutions architect",
        "cloud migration specialist",
        "digital transformation consultant",
        "process engineer",
        "platform engineer",
        "devops analyst",
        "reliability analyst",
        "infrastructure analyst",
    ],
    "IS Research": [
        "is research assistant",
        "ai research assistant",
        "research associate",
        "academic research analyst",
        "phd",
        "pre-phd",
        "professor",
        "information systems research",
        "human ai interaction research",
        "ai governance research",
        "doctoral research",
        "university research",
    ],
}

# Titles that are unambiguously MSIS-relevant. Matching one is a strong signal.
STRONG_TITLE_KEYWORDS = [
    "business analyst",
    "data analyst",
    "security analyst",
    "product analyst",
    "systems analyst",
    "system analyst",
    "technology consultant",
    "solutions engineer",
    "solution engineer",
    "sap consultant",
    "cloud solutions analyst",
    "cloud solutions architect",
    "business intelligence analyst",
    "cybersecurity analyst",
    "risk analyst",
    "analytics engineer",
]

EARLY_CAREER_INDICATORS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "new grad",
    "new graduate",
    "university graduate",
    "rotational",
    "rotation program",
    "associate",
    "analyst",
    "entry level",
    "entry-level",
    "campus",
    "early career",
    "early-career",
    "graduate program",
    "university program",
]

TOOL_SKILL_KEYWORDS = [
    "sql",
    "python",
    "tableau",
    "power bi",
    "snowflake",
    "aws",
    "azure",
    "gcp",
    "sap",
    "salesforce",
    "workday",
    "servicenow",
    "databricks",
    "looker",
    "kubernetes",
]

BROAD_SIGNAL_KEYWORDS = [
    "consulting",
    "consultant",
    "transformation",
    "implementation",
    "platform",
    "enterprise applications",
    "enterprise application",
    "analytics",
    "cloud",
    "security",
    "risk",
    "artificial intelligence",
    "data",
    "information systems",
    "digital",
]

# Applied against the TITLE only (per project rules: do not down-rank a role just
# because "senior" appears in a description sentence).
SENIOR_TITLE_KEYWORDS = [
    "senior director",
    "sr director",
    "director",
    "vp",
    "vice president",
    "executive",
    "chief",
    "head of",
    "principal",
    "staff ",
    "distinguished",
    "fellow",
]

# Clearly-unrelated domains. Matched against the TITLE to avoid false negatives
# from incidental mentions in a description.
UNRELATED_DOMAIN_KEYWORDS = [
    "nurse",
    "physician",
    "warehouse associate",
    "warehouse",
    "cashier",
    "driver",
    "account executive",
    "legal counsel",
    "attorney",
    "paralegal",
    "hardware technician",
    "mechanical engineer",
    "civil engineer",
    "electrician",
    "welder",
    "chef",
    "barista",
    "custodian",
    "recruiter",
    "phlebotomist",
    "pharmacist",
    "dental",
    "veterinar",
]


@dataclass(frozen=True)
class RelevanceResult:
    """Outcome of scoring one posting for MSIS relevance."""

    score: int
    is_relevant: bool
    matched_keywords: list[str] = field(default_factory=list)
    concentration_hints: list[str] = field(default_factory=list)
    career_stage: str = "unknown"
    reasons: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def _contains(text: str, keyword: str) -> bool:
    """Word-boundary-aware substring match (handles multi-word phrases)."""

    escaped = re.escape(keyword.casefold().strip())
    if not escaped:
        return False
    return re.search(rf"(?<!\w){escaped}(?!\w)", text) is not None


def _matches(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if _contains(text, keyword)]


def detect_career_stage(title: str, description: str = "") -> str:
    """Classify a posting into a coarse career stage.

    Returns one of: internship, entry_level, early_career, mid_level, senior,
    unknown.
    """

    title_text = _norm(title)
    combined = f"{title_text} {_norm(description)}"

    if _matches(title_text, ["intern", "internship", "co-op", "coop"]) or _contains(
        combined, "internship"
    ):
        return "internship"
    if _matches(
        title_text,
        [
            "new grad",
            "new graduate",
            "university graduate",
            "entry level",
            "entry-level",
            "campus",
            "graduate program",
            "university program",
        ],
    ):
        return "entry_level"
    if _matches(title_text, SENIOR_TITLE_KEYWORDS):
        return "senior"
    if _contains(title_text, "senior") or _contains(title_text, "sr."):
        return "senior"
    if _matches(title_text, ["associate", "analyst", "rotational", "early career"]):
        return "early_career"
    return "unknown"


def score_relevance(
    title: str,
    description: str = "",
    *,
    threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
    keywords_override: list[str] | None = None,
) -> RelevanceResult:
    """Score a posting for MSIS relevance using deterministic keyword rules."""

    title_text = _norm(title)
    description_text = _norm(description)
    combined = f"{title_text} {description_text}".strip()

    matched: list[str] = []
    reasons: list[str] = []
    score = 0

    def record(keywords: list[str], label: str) -> list[str]:
        found = _matches(combined, keywords)
        for keyword in found:
            if keyword not in matched:
                matched.append(keyword)
        if found:
            reasons.append(f"{label}: {', '.join(dict.fromkeys(found))}")
        return found

    # +3 strong title match (title only).
    strong_title = _matches(title_text, STRONG_TITLE_KEYWORDS)
    if strong_title:
        score += 3
        for keyword in strong_title:
            if keyword not in matched:
                matched.append(keyword)
        reasons.append(f"strong title match (+3): {', '.join(strong_title)}")

    # +2 official concentration-specific keyword in title or description.
    concentration_hints: list[str] = []
    for concentration in MSIS_CONCENTRATIONS:
        family = CONCENTRATION_KEYWORD_FAMILIES.get(concentration, [])
        found = _matches(combined, family)
        if found:
            concentration_hints.append(concentration)
            for keyword in found:
                if keyword not in matched:
                    matched.append(keyword)
    if concentration_hints:
        score += 2
        reasons.append(f"concentration keywords (+2): {', '.join(concentration_hints)}")

    # +2 early-career indicators.
    if record(EARLY_CAREER_INDICATORS, "early-career (+2)"):
        score += 2

    # +1 tools/skills.
    if record(TOOL_SKILL_KEYWORDS, "tools/skills (+1)"):
        score += 1

    # +1 broad relevant signal.
    if record(BROAD_SIGNAL_KEYWORDS, "broad signal (+1)"):
        score += 1

    # Optional per-company keyword boost.
    if keywords_override:
        override_hits = _matches(combined, [k.casefold() for k in keywords_override])
        if override_hits:
            score += 1
            for keyword in override_hits:
                if keyword not in matched:
                    matched.append(keyword)
            reasons.append(f"company keyword override (+1): {', '.join(override_hits)}")

    # -3 senior-only/director/principal/staff/executive titles.
    senior_hits = _matches(title_text, SENIOR_TITLE_KEYWORDS)
    if senior_hits or _contains(title_text, "senior"):
        score -= 3
        reasons.append("senior/leadership title (-3)")

    # -4 clearly unrelated domains (title only).
    unrelated_hits = _matches(title_text, UNRELATED_DOMAIN_KEYWORDS)
    # "research scientist" is only unrelated when there is no IS Research signal.
    if _contains(title_text, "research scientist") and (
        "IS Research" not in concentration_hints
    ):
        unrelated_hits = [*unrelated_hits, "research scientist"]
    if unrelated_hits:
        score -= 4
        reasons.append(f"unrelated domain (-4): {', '.join(unrelated_hits)}")

    career_stage = detect_career_stage(title, description)
    is_relevant = score >= threshold

    return RelevanceResult(
        score=score,
        is_relevant=is_relevant,
        matched_keywords=matched,
        concentration_hints=concentration_hints,
        career_stage=career_stage,
        reasons=reasons,
    )

"""Detect public ATS endpoints from employer career-page HTML.

Used by the coverage research workflow (``scripts/research_lamp_companies.py``)
to map an employer's public careers page to a supported ATS provider and its
identifier. Detection is regex-based over the page source only — no login,
no JavaScript execution, no bypassing of any access control.

Two kinds of signals are recognized:

* Supported providers (an adapter exists): Greenhouse, Lever, Ashby,
  SmartRecruiters, Workday, Oracle Recruiting Cloud. Phenom-hosted pages that
  expose ``*.myworkdayjobs.com`` apply links resolve to Workday.
* Unsupported markers (no compliant public JSON board adapter yet): iCIMS,
  SuccessFactors, Taleo, Eightfold, Avature, Phenom. These are surfaced so the
  coverage report can record *why* an employer stays disabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Providers detectable with an identifier that our adapters can consume.
_SUPPORTED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "greenhouse",
        re.compile(
            r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?"
            r"(?P<slug>[A-Za-z0-9_-]+)"
        ),
    ),
    (
        "greenhouse",
        re.compile(r"job-boards\.greenhouse\.io/(?P<slug>[A-Za-z0-9_-]+)"),
    ),
    (
        "lever",
        re.compile(
            r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?(?P<slug>[A-Za-z0-9_-]+)"
        ),
    ),
    (
        "ashby",
        re.compile(
            r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/"
            r"(?P<slug>[A-Za-z0-9_-]+)"
        ),
    ),
    (
        "smartrecruiters",
        re.compile(
            r"(?:jobs|careers|api)\.smartrecruiters\.com/(?:v1/companies/)?"
            r"(?P<slug>[A-Za-z0-9]+)"
        ),
    ),
    (
        "workday",
        re.compile(
            r"(?P<host>[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)"
            r"(?:/(?:wday/cxs/(?P<tenant>[a-z0-9_-]+)/)?(?:[a-z]{2}-[A-Z]{2}/)?"
            r"(?P<site>[A-Za-z0-9_-]+))?"
        ),
    ),
    (
        "oraclecloud",
        re.compile(
            r"(?P<host>[a-z0-9-]+\.fa\.[a-z0-9-]+\.oraclecloud\.com)"
            r"(?:/hcmUI/CandidateExperience/[a-z-]+/sites/(?P<site>CX_[0-9]+))?"
        ),
    ),
]

# ATS platforms we can identify but cannot fetch compliantly today.
_UNSUPPORTED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("icims", re.compile(r"[a-z0-9-]+\.icims\.com")),
    (
        "successfactors",
        re.compile(
            r"(?:successfactors\.(?:com|eu)|(?:jobs|careers?)\.sap\.com|rmk\.sf\.)"
        ),
    ),
    ("taleo", re.compile(r"[a-z0-9.]+\.taleo\.net")),
    ("eightfold", re.compile(r"(?:eightfold\.ai|\.jobs\.[a-z0-9-]+\.net/careers)")),
    ("avature", re.compile(r"[a-z0-9-]+\.avature\.net")),
    (
        "phenom",
        re.compile(r"(?:phenompeople\.com|phenom\.com/px|widget\.phenompeople)"),
    ),
]

# Workday "site" path segments that are locale or infrastructure, not sites.
_WORKDAY_NON_SITE_SEGMENTS = frozenset({"wday", "en-us", "job", "jobs", "login", "cxs"})


@dataclass(frozen=True)
class ATSCandidate:
    """One detected ATS endpoint candidate for an employer."""

    provider: str
    supported: bool
    slug: str | None = None
    host: str | None = None
    tenant: str | None = None
    site: str | None = None
    evidence: str = ""

    def key(self) -> tuple[str, str | None, str | None, str | None, str | None]:
        return (self.provider, self.slug, self.host, self.tenant, self.site)


@dataclass
class DiscoveryResult:
    """All ATS candidates detected in one page."""

    candidates: list[ATSCandidate] = field(default_factory=list)

    @property
    def supported(self) -> list[ATSCandidate]:
        return [c for c in self.candidates if c.supported]

    @property
    def unsupported_markers(self) -> list[str]:
        return sorted({c.provider for c in self.candidates if not c.supported})


def detect_ats_candidates(html: str) -> DiscoveryResult:
    """Scan page source for public ATS endpoint patterns."""

    result = DiscoveryResult()
    if not html:
        return result
    seen: set[tuple[str, str | None, str | None, str | None, str | None]] = set()

    for provider, pattern in _SUPPORTED_PATTERNS:
        for match in pattern.finditer(html):
            groups = match.groupdict()
            site = groups.get("site")
            if provider == "workday" and site:
                if site.casefold() in _WORKDAY_NON_SITE_SEGMENTS:
                    site = None
            candidate = ATSCandidate(
                provider=provider,
                supported=True,
                slug=groups.get("slug"),
                host=groups.get("host"),
                tenant=groups.get("tenant"),
                site=site,
                evidence=match.group(0)[:200],
            )
            if candidate.key() in seen:
                continue
            seen.add(candidate.key())
            result.candidates.append(candidate)

    for provider, pattern in _UNSUPPORTED_PATTERNS:
        unsupported_match = pattern.search(html)
        if unsupported_match is None:
            continue
        candidate = ATSCandidate(
            provider=provider,
            supported=False,
            evidence=unsupported_match.group(0)[:200],
        )
        if candidate.key() not in seen:
            seen.add(candidate.key())
            result.candidates.append(candidate)

    return result

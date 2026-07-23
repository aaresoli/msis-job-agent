"""Shared provider contract and parsing helpers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html import unescape
from typing import Any

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.http import HttpClient


class ProviderError(RuntimeError):
    """Raised when a provider cannot fetch or parse a company's postings."""


class ProviderNotImplementedError(ProviderError):
    """Raised for providers that exist as an interface but are not yet supported."""


@dataclass(frozen=True)
class RawJob:
    """Provider-neutral posting, prior to relevance scoring and normalization."""

    source_job_id: str
    title: str
    company: str
    url: str
    location: str | None = None
    description: str = ""
    apply_url: str | None = None
    employment_type: str | None = None
    department: str | None = None
    location_type: str | None = None
    compensation: str | None = None
    posted_date: date | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Contract for a single ATS provider adapter."""

    name: str

    @abstractmethod
    def primary_endpoint(self, target: CompanyTarget) -> str:
        """Return the main list endpoint (used for robots checks and logging)."""

    @abstractmethod
    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        """Fetch raw postings for one configured company."""

    def _require(
        self, value: str | None, field_name: str, target: CompanyTarget
    ) -> str:
        if not value or not value.strip():
            raise ProviderError(
                f"{self.name} adapter requires '{field_name}' for company "
                f"'{target.company_name}'"
            )
        return value.strip()


# How many strip/unescape rounds clean_html will run. Two is enough for the
# entity-encoded HTML seen in the wild; the third exists only so the loop can
# observe that nothing changed and stop.
_MAX_UNESCAPE_ROUNDS = 3


def _strip_tags(text: str) -> str:
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", text)
    text = re.sub(r"(?i)</\s*(p|li|div|tr|h[1-6]|ul|ol)\s*>", " ", text)
    return re.sub(r"<[^>]+>", " ", text)


def clean_html(value: Any) -> str:
    """Convert HTML/entity-encoded description text into readable plain text.

    Stripping and unescaping alternate rather than running once each, because
    some boards return *entity-encoded* HTML. Greenhouse's ``content`` field
    arrives as ``&lt;div class=&quot;pay-range&quot;&gt;...``: a single strip
    pass finds no literal tags, and the unescape that followed then turned the
    entities back into markup that nothing removed. Every Greenhouse posting in
    the corpus reached the database with its tags intact.

    That is not only cosmetic. The description is what gets embedded, what the
    enrichment model reads, and what a student sees. The model quotes the
    *rendered* salary ("$269,800 — $370,900 USD") while the stored text still
    held ``<span>$269,800</span>``, so the verbatim-quote check could never
    match and the posting was routed to review.
    """

    if value is None:
        return ""
    text = str(value)
    for _ in range(_MAX_UNESCAPE_ROUNDS):
        stripped = _strip_tags(text)
        unescaped = unescape(stripped)
        if unescaped == text:
            break
        text = unescaped
    # A final strip in case the last unescape exposed one more layer of markup.
    text = _strip_tags(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: Any) -> date | None:
    """Parse a variety of ATS date encodings into a ``date``.

    Supports ISO-8601 date/datetime strings (with or without ``Z``) and integer
    epoch milliseconds. Returns ``None`` when the value cannot be parsed.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # Heuristic: treat large integers as epoch milliseconds.
        try:
            seconds = float(value)
            if seconds > 1e11:
                seconds /= 1000.0
            return datetime.fromtimestamp(seconds, UTC).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None

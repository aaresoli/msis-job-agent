"""Interpretable location matching for the ranker.

Student geo preferences use informal region labels and city nicknames (for
example "Midwest (Chicago, Indy, Cincy)"), while postings use "City, ST"
strings. This module expands preferences into concrete city terms and matches
them against a posting location. It is a small, extensible lookup — not
geocoding — and is deliberately conservative: it only reports a match when a
known term is found.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# City nicknames/abbreviations -> canonical city terms that appear in postings.
CITY_ALIASES: dict[str, list[str]] = {
    "indy": ["indianapolis"],
    "nyc": ["new york"],
    "cincy": ["cincinnati"],
    "cinci": ["cincinnati"],
    "dc": ["washington"],
    "d.c.": ["washington"],
    "sf": ["san francisco"],
    "bay area": ["san francisco", "oakland", "san jose"],
    "socal": ["los angeles", "san diego", "irvine"],
    "la": ["los angeles"],
    "philly": ["philadelphia"],
    "atl": ["atlanta"],
    "nola": ["new orleans"],
}

# Broad region labels -> representative city terms.
REGION_CITIES: dict[str, list[str]] = {
    "midwest": [
        "chicago",
        "indianapolis",
        "cincinnati",
        "columbus",
        "detroit",
        "minneapolis",
        "st. louis",
        "kansas city",
        "milwaukee",
    ],
    "east coast": [
        "new york",
        "boston",
        "washington",
        "philadelphia",
        "baltimore",
    ],
    "northeast": ["new york", "boston", "philadelphia"],
    "west coast": [
        "san francisco",
        "seattle",
        "los angeles",
        "san jose",
        "portland",
    ],
    "south": [
        "atlanta",
        "dallas",
        "houston",
        "austin",
        "charlotte",
        "nashville",
    ],
    "southeast": ["atlanta", "charlotte", "miami", "nashville"],
}


def expand_geo_terms(geo_preference: Iterable[str]) -> list[str]:
    """Expand student geo preferences into concrete, matchable city terms."""

    terms: list[str] = []
    for preference in geo_preference:
        text = preference.strip().casefold()
        if not text:
            continue
        region, _, inside = text.partition("(")
        raw_tokens = [region.strip()]
        raw_tokens.extend(token.strip() for token in inside.rstrip(")").split(","))
        for token in raw_tokens:
            if not token:
                continue
            for region_name, cities in REGION_CITIES.items():
                if region_name in token:
                    terms.extend(cities)
            if token in CITY_ALIASES:
                terms.extend(CITY_ALIASES[token])
            if len(token) >= 3:
                terms.append(token)
    return list(dict.fromkeys(terms))


def resolve_location_match(
    location: str,
    geo_preference: Iterable[str],
) -> str | None:
    """Return the matched location term for a posting, or None if unknown."""

    normalized = location.casefold()
    for term in expand_geo_terms(geo_preference):
        if _contains_location_term(normalized, term):
            return term
    return None


def _contains_location_term(location: str, term: str) -> bool:
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return re.search(pattern, location) is not None

"""U.S.-location detection shared by ingestion and the dashboard.

ATS location values are free text and frequently omit a structured country.
For a U.S.-only job feed, failing open is unsafe: ``"Remote"`` may mean
worldwide and an unknown site code may be anywhere.  ``is_us_location``
therefore requires affirmative U.S. evidence rather than trying to enumerate
every possible foreign location.
"""

from __future__ import annotations

import re

US_COUNTRY_PHRASES: frozenset[str] = frozenset(
    {
        "united states",
        "united states of america",
        "us",
        "usa",
        "u.s.a",
        "u.s.",
        "u.s",
    }
)

US_STATE_AND_TERRITORY_NAMES: frozenset[str] = frozenset(
    {
        "alabama",
        "alaska",
        "american samoa",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "district of columbia",
        "florida",
        "georgia",
        "guam",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "new hampshire",
        "new jersey",
        "new mexico",
        "new york",
        "north carolina",
        "north dakota",
        "northern mariana islands",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "puerto rico",
        "rhode island",
        "south carolina",
        "south dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virgin islands",
        "virginia",
        "washington",
        "west virginia",
        "wisconsin",
        "wyoming",
    }
)

US_STATE_AND_TERRITORY_CODES: frozenset[str] = frozenset(
    {
        "al",
        "ak",
        "as",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "dc",
        "de",
        "fl",
        "ga",
        "gu",
        "hi",
        "id",
        "il",
        "in",
        "ia",
        "ks",
        "ky",
        "la",
        "me",
        "md",
        "ma",
        "mi",
        "mn",
        "ms",
        "mo",
        "mp",
        "mt",
        "ne",
        "nv",
        "nh",
        "nj",
        "nm",
        "ny",
        "nc",
        "nd",
        "oh",
        "ok",
        "or",
        "pa",
        "pr",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "vt",
        "vi",
        "va",
        "wa",
        "wv",
        "wi",
        "wy",
    }
)

# An explicit foreign country wins over a coincidental U.S. state name or
# code (for example ``"Georgia, Europe"`` or ``"Ontario, CA, Canada"``).
NON_US_COUNTRY_PHRASES: frozenset[str] = frozenset(
    {
        "argentina",
        "australia",
        "austria",
        "bangladesh",
        "belgium",
        "brazil",
        "bulgaria",
        "canada",
        "chile",
        "china",
        "colombia",
        "costa rica",
        "croatia",
        "czech republic",
        "czechia",
        "denmark",
        "egypt",
        "england",
        "estonia",
        "finland",
        "france",
        "germany",
        "greece",
        "hong kong",
        "hungary",
        "iceland",
        "india",
        "indonesia",
        "ireland",
        "israel",
        "italy",
        "jamaica",
        "japan",
        "kenya",
        "latvia",
        "lithuania",
        "luxembourg",
        "malaysia",
        "mexico",
        "morocco",
        "nepal",
        "netherlands",
        "new zealand",
        "nigeria",
        "northern ireland",
        "norway",
        "pakistan",
        "panama",
        "peru",
        "philippines",
        "poland",
        "portugal",
        "qatar",
        "romania",
        "russia",
        "saudi arabia",
        "scotland",
        "serbia",
        "singapore",
        "slovakia",
        "slovenia",
        "south africa",
        "south korea",
        "spain",
        "sri lanka",
        "sweden",
        "switzerland",
        "taiwan",
        "thailand",
        "turkey",
        "uae",
        "ukraine",
        "united arab emirates",
        "united kingdom",
        "vietnam",
        "wales",
    }
)


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _location_tokens(text: str) -> list[str]:
    """Split common ATS formats without treating words such as 'in' as codes."""

    return [
        token.strip()
        for token in re.split(r"\s*(?:[,/;|]|\s+-\s+)\s*", text)
        if token.strip()
    ]


def is_us_location(location: str | None) -> bool:
    """Return whether a location contains affirmative evidence it is in the U.S."""

    normalized = (location or "").casefold().strip()
    if not normalized:
        return False

    if any(_has_phrase(normalized, phrase) for phrase in US_COUNTRY_PHRASES):
        return True
    if "us" in _location_tokens(normalized):
        return True

    if any(_has_phrase(normalized, phrase) for phrase in NON_US_COUNTRY_PHRASES):
        return False

    if any(_has_phrase(normalized, name) for name in US_STATE_AND_TERRITORY_NAMES):
        return True

    for token in _location_tokens(normalized):
        # Allow the common ``IL 60601`` form while keeping short codes bounded
        # to a complete location component.
        code = token.split(maxsplit=1)[0]
        if code in US_STATE_AND_TERRITORY_CODES and (
            token == code or re.fullmatch(rf"{code} \d{{5}}(?:-\d{{4}})?", token)
        ):
            return True
    return False


def is_explicitly_non_us(location: str | None) -> bool:
    """Backward-compatible foreign-location check for existing callers.

    Unknown locations are not *explicitly* foreign, even though they do not
    satisfy the stricter U.S.-only policy implemented by ``is_us_location``.
    """

    normalized = (location or "").casefold().strip()
    if not normalized or is_us_location(normalized):
        return False
    return any(_has_phrase(normalized, phrase) for phrase in NON_US_COUNTRY_PHRASES)

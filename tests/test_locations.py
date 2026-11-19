from hope_job_agent.scoring.locations import expand_geo_terms, resolve_location_match


def test_expand_geo_terms_resolves_nicknames_and_regions():
    terms = expand_geo_terms(["Midwest (Chicago, Indy, Cincy)"])

    # Region expansion plus nickname expansion produce canonical city terms.
    assert "chicago" in terms
    assert "indianapolis" in terms
    assert "cincinnati" in terms


def test_resolve_location_match_handles_nickname_to_full_city():
    assert resolve_location_match(
        "Indianapolis, IN", ["Midwest (Chicago, Indy, Cincy)"]
    ) in {"indianapolis", "chicago", "cincinnati"}
    assert (
        resolve_location_match("Indianapolis, IN", ["East Coast (NYC, Boston, DC)"])
        is None
    )


def test_resolve_location_match_handles_multiword_cities():
    assert (
        resolve_location_match("New York, NY", ["East Coast (NYC, Boston, DC)"])
        == "new york"
    )
    assert resolve_location_match("San Francisco, CA", ["Bay Area"]) == "san francisco"


def test_resolve_location_match_returns_none_for_unknown():
    assert resolve_location_match("Not specified", ["Midwest (Indy)"]) is None
    assert resolve_location_match("Chicago, IL", []) is None

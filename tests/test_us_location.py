from hope_job_agent.utils.us_location import is_explicitly_non_us, is_us_location


def test_explicit_foreign_country_is_rejected():
    assert is_explicitly_non_us("Bengaluru, Karnataka, India") is True
    assert is_explicitly_non_us("London, United Kingdom") is True
    assert is_explicitly_non_us("Toronto, ON, Canada") is True


def test_us_locations_are_not_rejected():
    assert is_explicitly_non_us("Chicago, IL") is False
    assert is_explicitly_non_us("Austin, TX, United States") is False
    assert is_explicitly_non_us("Georgia") is False  # US state, not the country


def test_ambiguous_or_blank_locations_are_not_rejected():
    assert is_explicitly_non_us("") is False
    assert is_explicitly_non_us("Remote") is False
    assert is_explicitly_non_us("Not specified") is False


def test_us_location_requires_affirmative_us_evidence():
    assert is_us_location("Chicago, IL") is True
    assert is_us_location("Austin, TX 78701") is True
    assert is_us_location("Remote - US") is True
    assert is_us_location("Remote (US)") is True
    assert is_us_location("US Remote") is True
    assert is_us_location("United States") is True
    assert is_us_location("San Juan, Puerto Rico") is True


def test_us_location_rejects_foreign_unknown_and_unspecified_remote():
    assert is_us_location("Bengaluru, Karnataka, India") is False
    assert is_us_location("Ontario, CA, Canada") is False
    assert is_us_location("Remote") is False
    assert is_us_location("Not specified") is False
    assert is_us_location("") is False

import json

import pytest

from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfigError,
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.registry import registered_providers

_SAMPLE = {
    "fetch_policy": {"min_interval_seconds": 0.0, "max_jobs_per_company": 50},
    "relevance_threshold": 4,
    "companies": [
        {"company_name": "Acme", "ats_provider": "Greenhouse", "ats_slug": "acme"},
        {
            "company_name": "Beta",
            "ats_provider": "lever",
            "ats_slug": "beta",
            "enabled": False,
            "priority": 5,
        },
    ],
}


def test_loads_json_config(tmp_path):
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(_SAMPLE), encoding="utf-8")

    config = load_company_careers_config(path)

    assert config.relevance_threshold == 4
    assert config.fetch_policy.max_jobs_per_company == 50
    assert len(config.companies) == 2
    # ats_provider is normalized to lowercase.
    assert config.companies[0].ats_provider == "greenhouse"
    # Only enabled companies are returned by enabled_companies().
    assert [c.company_name for c in config.enabled_companies()] == ["Acme"]


def test_loads_yaml_config(tmp_path):
    pytest.importorskip("yaml")
    import yaml

    path = tmp_path / "companies.yml"
    path.write_text(yaml.safe_dump(_SAMPLE), encoding="utf-8")

    config = load_company_careers_config(path)

    assert len(config.companies) == 2


def test_missing_file_raises(tmp_path):
    with pytest.raises(CompanyCareersConfigError):
        load_company_careers_config(tmp_path / "nope.yml")


def test_unknown_field_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {"company_name": "X", "ats_provider": "greenhouse", "bogus": 1}
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompanyCareersConfigError):
        load_company_careers_config(path)


def test_shipped_config_is_valid_and_uses_known_providers():
    config = load_company_careers_config("config/company_careers.yml")

    enabled = config.enabled_companies()
    assert 15 <= len(enabled) <= 25
    known = set(registered_providers())
    for company in enabled:
        assert company.ats_provider in known
        # iCIMS has no implementation; it must not be enabled.
        assert company.ats_provider != "icims"

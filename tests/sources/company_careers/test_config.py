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
    # Top-50 coverage grew the enabled list; there is deliberately no upper cap.
    assert len(enabled) >= 15
    known = set(registered_providers())
    for company in enabled:
        assert company.ats_provider in known
        # iCIMS has no implementation; it must not be enabled.
        assert company.ats_provider != "icims"


def test_enabled_top50_company_must_be_verified(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company_name": "X",
                        "ats_provider": "greenhouse",
                        "ats_slug": "x",
                        "enabled": True,
                        "student_interest_rank": 1,
                        "verification_status": "pending",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompanyCareersConfigError):
        load_company_careers_config(path)


def test_unsupported_status_requires_reason(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company_name": "X",
                        "ats_provider": "static",
                        "enabled": False,
                        "verification_status": "unsupported",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompanyCareersConfigError):
        load_company_careers_config(path)


def test_invalid_verification_status_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company_name": "X",
                        "ats_provider": "static",
                        "enabled": False,
                        "verification_status": "maybe",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompanyCareersConfigError):
        load_company_careers_config(path)


def test_verification_metadata_roundtrip(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company_name": "Acme",
                        "ats_provider": "greenhouse",
                        "ats_slug": "acme",
                        "enabled": True,
                        "student_interest_rank": 3,
                        "student_interest_count": 81,
                        "industry": "Accounting / Professional Services",
                        "verification_status": "verified",
                        "verified_at": "2026-07-08",
                        "verification_source_url": (
                            "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = load_company_careers_config(path)
    company = config.companies[0]
    assert company.student_interest_rank == 3
    assert company.student_interest_count == 81
    assert company.verification_status == "verified"
    assert company.verified_at == "2026-07-08"


# Excel ranks merged into a better-ranked canonical entry during alias
# normalization (see COMPANY_ALIASES in scripts/research_lamp_companies.py):
# 109 "Slalom Consulting" -> rank 93 "Slalom",
# 110 "TCS" -> rank 78 "Tata Consultancy Services",
# 235 "Eli Lilly and Company" -> rank 16 (exact duplicate row),
# 247 "Hewlett Packard Enterprise (HPE)" -> rank 142.
MERGED_ALIAS_RANKS = {109, 110, 235, 247}


def test_shipped_config_covers_all_ranked_lamp_companies():
    config = load_company_careers_config("config/company_careers.yml")

    tracked = {
        c.student_interest_rank: c
        for c in config.companies
        if c.student_interest_rank is not None
    }
    assert set(tracked) == set(range(1, 301)) - MERGED_ALIAS_RANKS
    for company in tracked.values():
        if company.enabled:
            assert company.verification_status == "verified"
            assert company.verified_at is not None
        else:
            assert company.verification_status in {"pending", "unsupported"}
            if company.verification_status == "unsupported":
                assert company.unsupported_reason


def test_shipped_config_accounts_for_all_300_excel_ranks():
    from hope_job_agent.sources.company_careers.adapter import (
        compute_coverage_summary,
    )

    config = load_company_careers_config("config/company_careers.yml")
    summary = compute_coverage_summary(config)

    # 296 entries + 4 merged aliases account for every Excel rank 1-300.
    assert summary["ranks_covered_total"] == 300
    assert summary["merged_alias_ranks"] == {
        109: "Slalom",
        110: "Tata Consultancy Services",
        235: "Eli Lilly and Company",
        247: "Hewlett Packard Enterprise",
    }


def test_ranks_are_unique_in_shipped_config():
    config = load_company_careers_config("config/company_careers.yml")

    ranks = [
        c.student_interest_rank
        for c in config.companies
        if c.student_interest_rank is not None
    ]
    assert len(ranks) == len(set(ranks))


def test_duplicate_enabled_endpoints_rejected(tmp_path):
    path = tmp_path / "dup.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company_name": "Slalom",
                        "ats_provider": "greenhouse",
                        "ats_slug": "slalom",
                    },
                    {
                        "company_name": "Slalom Consulting",
                        "ats_provider": "greenhouse",
                        "ats_slug": "Slalom",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompanyCareersConfigError):
        load_company_careers_config(path)


def test_duplicate_endpoint_allowed_when_one_is_disabled(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company_name": "Slalom",
                        "ats_provider": "greenhouse",
                        "ats_slug": "slalom",
                    },
                    {
                        "company_name": "Slalom Consulting",
                        "ats_provider": "greenhouse",
                        "ats_slug": "slalom",
                        "enabled": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config = load_company_careers_config(path)
    assert len(config.enabled_companies()) == 1

"""Tests for the official MSIS concentration migration and alias normalization."""

import pytest

from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.classification.taxonomy import (
    normalize_concentration,
    normalize_concentrations,
)
from hope_job_agent.models.job import JobPosting

OFFICIAL = {
    "Data Analytics and AI",
    "Cybersecurity and Risk Analytics",
    "Digital Enterprise Systems and AI",
    "Digital Platforms and Security",
    "IS Research",
}

OUTDATED_NAMES = {
    "Business Intelligence and Analytics",
    "Enterprise Systems",
    "Digital Enterprise Systems",
    "IT Strategy and Management",
    "Technology Architecture",
    "Digital Innovation",
    "Business Analytics",
}


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("Business Intelligence and Analytics", "Data Analytics and AI"),
        ("Analytics", "Data Analytics and AI"),
        ("Data Analytics", "Data Analytics and AI"),
        ("AI", "Data Analytics and AI"),
        ("DAAI", "Data Analytics and AI"),
        ("Cybersecurity", "Cybersecurity and Risk Analytics"),
        ("Security", "Cybersecurity and Risk Analytics"),
        ("Risk Analytics", "Cybersecurity and Risk Analytics"),
        ("CRA", "Cybersecurity and Risk Analytics"),
        ("Enterprise Systems", "Digital Enterprise Systems and AI"),
        ("Digital Enterprise Systems", "Digital Enterprise Systems and AI"),
        ("DESAI", "Digital Enterprise Systems and AI"),
        ("ERP", "Digital Enterprise Systems and AI"),
        ("SAP", "Digital Enterprise Systems and AI"),
        ("Enterprise AI", "Digital Enterprise Systems and AI"),
        ("Digital Platforms", "Digital Platforms and Security"),
        ("Cloud Platforms", "Digital Platforms and Security"),
        ("Technology Architecture", "Digital Platforms and Security"),
        ("Platform Security", "Digital Platforms and Security"),
        ("DPS", "Digital Platforms and Security"),
        ("IS Research", "IS Research"),
        ("ISR", "IS Research"),
        ("Pre-PhD", "IS Research"),
        ("Research", "IS Research"),
        # Old four-track canonical names must map forward too.
        ("IT Strategy and Management", "Digital Enterprise Systems and AI"),
        ("Digital Innovation", "Digital Platforms and Security"),
    ],
)
def test_alias_maps_to_official_name(alias, expected):
    assert normalize_concentration(alias) == expected


def test_normalize_is_case_insensitive_and_handles_official_and_codes():
    assert (
        normalize_concentration("  data analytics AND ai ") == "Data Analytics and AI"
    )
    assert normalize_concentration("DES & AI") == "Digital Enterprise Systems and AI"
    assert normalize_concentration("cra") == "Cybersecurity and Risk Analytics"


def test_normalize_concentrations_dedupes_orders_and_drops_unknown():
    result = normalize_concentrations(
        ["Enterprise Systems", "ERP", "totally unknown", "Analytics"]
    )
    assert result == ["Data Analytics and AI", "Digital Enterprise Systems and AI"]


def test_normalize_unknown_returns_none():
    assert normalize_concentration("Underwater Basket Weaving") is None
    assert normalize_concentration("") is None
    assert normalize_concentration(None) is None


def _job(title, description, **overrides):
    defaults = {
        "source": "company_careers",
        "title": title,
        "company": "Example Employer",
        "location": "Indianapolis, IN",
        "description": description,
        "url": "https://example.com/jobs/x",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def test_classifier_output_never_uses_outdated_names():
    postings = [
        _job("Data Analyst Intern", "SQL and Tableau analytics dashboards."),
        _job("Security Analyst", "SOC, GRC, threat detection, incident response."),
        _job("Business Systems Analyst", "ERP and Salesforce enterprise applications."),
        _job(
            "Cloud Solutions Architect",
            "Cloud infrastructure engineer, platform security, IAM.",
        ),
        _job("AI Research Assistant", "Information systems research on AI governance."),
        # Postings pre-tagged with legacy names must normalize forward.
        _job(
            "Reporting Intern",
            "Executive reporting.",
            concentration_tags=["Business Analytics", "Enterprise Systems"],
        ),
        _job(
            "Platform Intern",
            "Cloud platform work.",
            concentration_tags=["Technology Architecture", "Digital Innovation"],
        ),
    ]

    for posting in postings:
        classified = classify_job_posting(posting)
        for tag in classified.concentration_tags:
            assert tag in OFFICIAL
            assert tag not in OUTDATED_NAMES

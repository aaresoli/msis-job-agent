from hope_job_agent.classification.classifier import classify_job, classify_job_posting
from hope_job_agent.models.job import JobPosting


def _job(title: str, description: str, **overrides) -> JobPosting:
    defaults = {
        "source": "employer_careers",
        "title": title,
        "company": "Example Employer",
        "location": "Indianapolis, IN",
        "description": description,
        "url": "https://example.com/jobs/example",
    }
    return JobPosting(**{**defaults, **overrides})


def test_classifies_data_analytics_and_bi_role():
    classification = classify_job(
        _job(
            "Data Analyst Intern",
            "Build SQL dashboards in Tableau and Power BI for business teams.",
        )
    )

    assert classification.role_tags == ["Data Analyst / BI Engineer"]
    assert classification.concentration_tags == [
        "Data Analytics and AI",
        "Information Systems Research in AI",
    ]


def test_classifies_cybersecurity_and_tech_risk_roles():
    classification = classify_job(
        _job(
            "Technology Risk Consultant",
            "Support NIST controls, SIEM monitoring, GRC, and security audits.",
        )
    )

    assert classification.role_tags == [
        "IT Consultant / Tech Risk",
        "Cybersecurity Analyst",
    ]
    assert classification.concentration_tags == [
        "Digital Transformation with AI",
        "Cybersecurity",
    ]


def test_classifies_digital_transformation_software_and_pm_signals():
    classification = classify_job(
        _job(
            "Software Engineer and Product Manager Rotation",
            "Ship cloud APIs, automate workflows, and manage agile delivery.",
        )
    )

    assert classification.role_tags == [
        "Product / Project Manager",
        "Software Engineer",
    ]
    assert classification.concentration_tags == ["Digital Transformation with AI"]


def test_normalizes_legacy_concentration_tags():
    classification = classify_job(
        _job(
            "Reporting Intern",
            "Create executive reporting for operational teams.",
            concentration_tags=["Business Analytics", "Enterprise Systems"],
        )
    )

    assert classification.concentration_tags == [
        "Data Analytics and AI",
        "Digital Transformation with AI",
    ]


def test_classify_job_posting_returns_tagged_copy_without_mutating_original():
    job = _job("Cybersecurity Analyst", "Investigate vulnerabilities and threats.")

    tagged_job = classify_job_posting(job)

    assert job.role_tags == []
    assert job.concentration_tags == []
    assert tagged_job.role_tags == ["Cybersecurity Analyst"]
    assert tagged_job.concentration_tags == ["Cybersecurity"]


def test_unknown_posting_receives_no_tags():
    classification = classify_job(
        _job(
            "Campus Assistant",
            "Help coordinate front desk coverage and event registration.",
        )
    )

    assert classification.role_tags == []
    assert classification.concentration_tags == []

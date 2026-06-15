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
    assert classification.role_confidence_scores["Data Analyst / BI Engineer"] > 0.8
    assert classification.concentration_tags == [
        "Data Analytics and AI",
        "Information Systems Research in AI",
    ]
    assert classification.is_uncertain is False


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
    assert classification.role_confidence_scores["IT Consultant / Tech Risk"] >= 0.5
    assert classification.concentration_confidence_scores["Cybersecurity"] >= 0.5


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
    assert tagged_job.role_confidence_scores["Cybersecurity Analyst"] >= 0.5
    assert tagged_job.concentration_confidence_scores["Cybersecurity"] >= 0.5
    assert tagged_job.classification_uncertain is False


def test_unknown_posting_falls_back_to_other_with_uncertainty():
    classification = classify_job(
        _job(
            "Campus Assistant",
            "Help coordinate front desk coverage and event registration.",
        )
    )

    assert classification.role_tags == ["Other"]
    assert classification.concentration_tags == []
    assert classification.role_confidence_scores == {"Other": 0.25}
    assert classification.concentration_confidence_scores == {}
    assert classification.is_uncertain is True
    assert classification.fallback_reason


def test_trusted_source_tags_receive_full_confidence():
    classification = classify_job(
        _job(
            "General Analyst",
            "Rotational role supporting multiple business teams.",
            role_tags=["Product / Project Manager"],
            concentration_tags=["Business Analytics"],
        )
    )

    assert classification.role_tags == ["Product / Project Manager"]
    assert classification.concentration_tags == [
        "Data Analytics and AI",
        "Digital Transformation with AI",
    ]
    assert classification.role_confidence_scores["Product / Project Manager"] == 1.0
    assert (
        classification.concentration_confidence_scores["Data Analytics and AI"]
        == 1.0
    )


def test_vague_analyst_role_is_marked_uncertain_without_role_fallback():
    classification = classify_job(
        _job(
            "Analyst Intern",
            "Support research, stakeholder notes, and operational reporting.",
        )
    )

    assert classification.role_tags == ["Other"]
    assert classification.is_uncertain is True

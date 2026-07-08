from hope_job_agent.classification.taxonomy import MSIS_CONCENTRATIONS
from hope_job_agent.sources.company_careers.relevance import (
    detect_career_stage,
    score_relevance,
)


def test_strong_title_and_early_career_are_relevant():
    result = score_relevance(
        "Data Analyst Intern",
        "Build SQL and Tableau dashboards for analytics teams.",
    )

    assert result.is_relevant is True
    assert result.score >= 3
    assert "Data Analytics and AI" in result.concentration_hints
    assert result.career_stage == "internship"
    assert "sql" in result.matched_keywords


def test_unrelated_role_is_filtered_out():
    result = score_relevance(
        "Registered Nurse",
        "Provide patient care in a clinical setting.",
    )

    assert result.is_relevant is False
    assert result.score < 3


def test_warehouse_role_is_filtered_out():
    result = score_relevance(
        "Warehouse Associate",
        "Pick, pack, and ship packages.",
    )

    assert result.is_relevant is False


def test_senior_title_is_penalized():
    result = score_relevance(
        "Senior Director, Field Operations",
        "Lead operations and strategy across regions.",
    )

    assert result.score < 3
    assert result.is_relevant is False
    assert result.career_stage == "senior"


def test_senior_word_in_description_does_not_penalize_relevant_title():
    result = score_relevance(
        "Business Analyst",
        "Work with senior stakeholders on SQL analytics and reporting.",
    )

    assert result.is_relevant is True
    assert result.career_stage != "senior"


def test_every_official_concentration_can_be_detected():
    samples = {
        "Data Analytics and AI": ("Data Analyst", "SQL, Python, Tableau analytics"),
        "Cybersecurity and Risk Analytics": (
            "Security Analyst",
            "SOC, GRC, incident response, threat detection",
        ),
        "Digital Enterprise Systems and AI": (
            "Business Systems Analyst",
            "ERP, SAP, Salesforce enterprise applications",
        ),
        "Digital Platforms and Security": (
            "Cloud Solutions Architect",
            "cloud infrastructure engineer, platform engineer, cloud security",
        ),
        "IS Research": (
            "AI Research Assistant",
            "information systems research and doctoral research on AI governance",
        ),
    }
    for concentration, (title, description) in samples.items():
        result = score_relevance(title, description)
        assert concentration in result.concentration_hints, concentration

    # Sanity: the sample keys cover exactly the official taxonomy.
    assert set(samples) == set(MSIS_CONCENTRATIONS)


def test_detect_career_stage_variants():
    assert detect_career_stage("Software Engineering Intern") == "internship"
    assert detect_career_stage("New Grad Analyst") == "entry_level"
    assert detect_career_stage("Associate Consultant") == "early_career"
    assert detect_career_stage("Principal Architect") == "senior"
    assert detect_career_stage("Widget Coordinator") == "unknown"


def test_msis_role_titles_from_lamp_pdf_are_relevant():
    # Role titles from "Industries_Companies_Job Titles_as of April 14_2025".
    samples = [
        ("Technology Risk Consultant", "Assess IT general controls and SOX compliance."),
        ("Digital Assurance Associate", "Support digital assurance engagements."),
        ("Workday Integrations Analyst", "Build Workday integration solutions."),
        ("SAP Supply Chain Analyst", "Support SAP supply chain modules."),
        ("ERP Consultant", "Implement ERP transformation programs."),
        ("ServiceNow Implementor", "Configure ServiceNow workflows."),
        ("Technology Architect Analyst", "Enterprise architecture analysis."),
        ("Internal IT Auditor", "Perform internal audit of IT systems."),
    ]
    for title, description in samples:
        result = score_relevance(title, description)
        assert result.is_relevant is True, title


def test_rotational_program_counts_as_early_career():
    result = score_relevance(
        "Corporate Finance Rotational Program",
        "Rotations across finance, analytics, and enterprise systems teams.",
    )
    assert result.career_stage in {"early_career", "entry_level", "unknown"}
    assert "rotational" in " ".join(result.matched_keywords)


def test_keywords_override_boosts_score():
    base = score_relevance("Coordinator", "Manage schedules and logistics.")
    boosted = score_relevance(
        "Coordinator",
        "Manage schedules and logistics.",
        keywords_override=["logistics"],
    )
    assert boosted.score > base.score

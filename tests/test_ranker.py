import json
from datetime import date
from pathlib import Path

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.scoring.ranker import (
    DEFAULT_RANKING_WEIGHTS,
    DEFAULT_RANKING_WEIGHTS_PATH,
    RankingWeightsConfigError,
    infer_seniority,
    load_ranking_weights,
    rank_jobs_for_student,
    score_job_for_student,
)


def test_ranking_gives_higher_score_to_more_relevant_jobs():
    student = StudentProfile(
        name="Test Student",
        concentration="Data Analytics and AI",
        target_roles=["data analyst"],
        skills=["SQL", "Python"],
        stage="internship search",
    )
    relevant_job = JobPosting(
        source="employer_careers",
        title="Data Analyst Intern",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Work with SQL, Python, dashboards, and business data.",
        url="https://example.com/jobs/data-analyst",
        concentration_tags=["Data Analytics and AI"],
    )
    less_relevant_job = JobPosting(
        source="employer_careers",
        title="Help Desk Assistant",
        company="Example Support",
        location="Bloomington, IN",
        description="Support internal users and document tickets.",
        url="https://example.com/jobs/help-desk",
        concentration_tags=["Digital Enterprise Systems and AI"],
    )

    assert score_job_for_student(student, relevant_job) > score_job_for_student(
        student, less_relevant_job
    )

    ranked = rank_jobs_for_student(student, [less_relevant_job, relevant_job])

    assert ranked[0].job.title == "Data Analyst Intern"
    assert isinstance(ranked[0].score, float)
    assert ranked[0].metadata["seniority"] == "Entry"


def test_ranking_rewards_cpt_opt_friendly_jobs_for_international_profiles():
    student = StudentProfile(
        name="International Student",
        concentration="Data Analytics and AI",
        academic_stage="Incoming student (Fall)",
        target_roles=["Data Analyst / BI Engineer"],
        skills=["SQL"],
        work_auth_status="Need CPT / OPT sponsorship",
    )
    friendly_job = JobPosting(
        source="employer_careers",
        title="Data Analyst Intern",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Work with SQL.",
        url="https://example.com/jobs/friendly",
        concentration_tags=["Data Analytics and AI"],
        role_tags=["Data Analyst / BI Engineer"],
        opt_cpt_flag=True,
    )
    unknown_job = friendly_job.model_copy(
        update={
            "url": "https://example.com/jobs/unknown",
            "opt_cpt_flag": None,
        }
    )

    ranked = rank_jobs_for_student(student, [unknown_job, friendly_job])

    assert ranked[0].job.url == friendly_job.url


def test_ranking_prioritizes_cpt_opt_friendly_jobs_for_international_profiles():
    student = StudentProfile(
        name="International Student",
        concentration="Data Analytics and AI",
        academic_stage="Incoming student (Fall)",
        target_roles=["Data Analyst / BI Engineer"],
        skills=["SQL", "Python"],
        work_auth_status="Need CPT / OPT sponsorship",
    )
    stronger_unknown_job = JobPosting(
        source="employer_careers",
        title="Data Analyst Intern",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Use SQL and Python for dashboard analytics.",
        url="https://example.com/jobs/stronger-unknown",
        concentration_tags=["Data Analytics and AI"],
        role_tags=["Data Analyst / BI Engineer"],
        opt_cpt_flag=None,
    )
    weaker_friendly_job = JobPosting(
        source="employer_careers",
        title="Operations Intern",
        company="Example Operations",
        location="Bloomington, IN",
        description="Support operations reporting.",
        url="https://example.com/jobs/weaker-friendly",
        opt_cpt_flag=True,
    )

    ranked = rank_jobs_for_student(student, [stronger_unknown_job, weaker_friendly_job])

    assert ranked[0].job.url == weaker_friendly_job.url
    assert ranked[0].score < ranked[1].score


def test_ranking_tie_breaks_by_recent_date_then_company_and_title():
    student = StudentProfile(
        name="Test Student",
        concentration="Data Analytics and AI",
        target_roles=[],
        skills=[],
    )
    older_job = JobPosting(
        source="employer_careers",
        title="Analyst B",
        company="Beta",
        location="Bloomington, IN",
        description="General analysis.",
        url="https://example.com/jobs/older",
        posted_date=date(2026, 5, 1),
    )
    newer_job = older_job.model_copy(
        update={
            "title": "Analyst C",
            "company": "Gamma",
            "url": "https://example.com/jobs/newer",
            "posted_date": date(2026, 6, 1),
        }
    )
    same_date_first_job = older_job.model_copy(
        update={
            "title": "Analyst A",
            "company": "Alpha",
            "url": "https://example.com/jobs/alpha",
        }
    )

    ranked = rank_jobs_for_student(
        student,
        [older_job, newer_job, same_date_first_job],
    )

    assert [match.job.url for match in ranked] == [
        "https://example.com/jobs/newer",
        "https://example.com/jobs/alpha",
        "https://example.com/jobs/older",
    ]


def test_location_signal_rewards_known_geo_and_remote_matches():
    geo_student = StudentProfile(
        name="Geo Student",
        concentration="Data Analytics and AI",
        target_roles=[],
        skills=[],
        geo_preference=["Midwest (Chicago, Indy, Cincy)"],
    )
    remote_student = StudentProfile(
        name="Remote Student",
        concentration="Data Analytics and AI",
        target_roles=[],
        skills=[],
        remote_preference="Online is fine",
    )
    chicago_job = JobPosting(
        source="employer_careers",
        title="Analyst",
        company="Example",
        location="Chicago, IL",
        description="General analysis work.",
        url="https://example.com/jobs/chicago",
    )
    remote_job = chicago_job.model_copy(
        update={"location": "Remote", "url": "https://example.com/jobs/remote"}
    )
    unknown_location_job = chicago_job.model_copy(
        update={"location": "Not specified", "url": "https://example.com/jobs/unknown"}
    )

    indy_job = chicago_job.model_copy(
        update={"location": "Indianapolis, IN", "url": "https://example.com/jobs/indy"}
    )

    location_weight = DEFAULT_RANKING_WEIGHTS.location_match
    assert score_job_for_student(geo_student, chicago_job) == location_weight
    # "Indy" nickname resolves to "Indianapolis" in the posting location.
    assert score_job_for_student(geo_student, indy_job) == location_weight
    assert score_job_for_student(remote_student, remote_job) == location_weight
    # Unknown location and unset preferences never score, so unknown is not a match.
    assert score_job_for_student(geo_student, unknown_location_job) == 0.0
    assert score_job_for_student(remote_student, chicago_job) == 0.0


def test_location_signal_appears_in_reasons_and_breakdown():
    from hope_job_agent.scoring.ranker import explain_job_score

    student = StudentProfile(
        name="Geo Student",
        concentration="Data Analytics and AI",
        target_roles=[],
        skills=[],
        geo_preference=["Midwest (Chicago, Indy, Cincy)"],
    )
    job = JobPosting(
        source="employer_careers",
        title="Analyst",
        company="Example",
        location="Chicago, IL",
        description="General analysis work.",
        url="https://example.com/jobs/chicago",
    )

    _score, reasons, metadata = explain_job_score(student, job)

    assert any("Location match" in reason for reason in reasons)
    breakdown = metadata["score_breakdown"]
    assert breakdown["location"] == DEFAULT_RANKING_WEIGHTS.location_match
    # Reasons are human-readable only; numeric per-signal labels live in metadata.
    assert not any(reason.startswith("Skill Score:") for reason in reasons)


def test_infer_seniority_treats_manager_intern_roles_as_entry_level():
    job = JobPosting(
        source="employer_careers",
        title="Product Manager Intern",
        company="Example Product",
        location="Bloomington, IN",
        description="Internship supporting product roadmap and launch planning.",
        url="https://example.com/jobs/product-manager-intern",
    )

    assert infer_seniority(job) == "Entry"


def test_checked_in_ranking_weights_match_default_rubric():
    assert load_ranking_weights(DEFAULT_RANKING_WEIGHTS_PATH) == DEFAULT_RANKING_WEIGHTS


def test_ranking_weights_config_can_change_scoring(tmp_path):
    config_path = tmp_path / "ranking_weights.json"
    config_path.write_text(
        json.dumps(
            {
                "skill_match": 10.0,
                "target_role_match": 0.0,
                "concentration_match": 0.0,
                "location_match": 0.0,
                "opt_cpt_match": 0.0,
                "seniority_match": 0.0,
                "seniority_mismatch_penalty": 0.0,
            }
        ),
        encoding="utf-8",
    )
    weights = load_ranking_weights(config_path)
    student = StudentProfile(
        name="Config Student",
        concentration="Data Analytics and AI",
        target_roles=[],
        skills=["SQL"],
    )
    job = JobPosting(
        source="employer_careers",
        title="Analyst",
        company="Example Analytics",
        location="Bloomington, IN",
        description="Build SQL reports.",
        url="https://example.com/jobs/config-score",
    )

    assert score_job_for_student(student, job, weights=weights) == 10.0


def test_ranking_weights_config_rejects_unknown_keys(tmp_path):
    config_path = tmp_path / "ranking_weights.json"
    config_path.write_text(
        json.dumps(
            {
                **DEFAULT_RANKING_WEIGHTS.__dict__,
                "unexpected_weight": 1.0,
            }
        ),
        encoding="utf-8",
    )

    try:
        load_ranking_weights(Path(config_path))
    except RankingWeightsConfigError as exc:
        assert "extra=['unexpected_weight']" in str(exc)
    else:
        raise AssertionError("Expected invalid ranking weights config to fail")

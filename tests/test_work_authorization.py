from hope_job_agent.classification.work_authorization import detect_work_authorization
from hope_job_agent.models.job import JobPosting


def _job(description: str, **overrides) -> JobPosting:
    defaults = {
        "source": "employer_careers",
        "title": "Data Analyst Intern",
        "company": "Example Analytics",
        "location": "Indianapolis, IN",
        "description": description,
        "url": "https://example.com/jobs/data-analyst",
    }
    return JobPosting(**{**defaults, **overrides})


def test_detects_cpt_opt_friendly_language():
    detection = detect_work_authorization(
        _job("International students using CPT or OPT are encouraged to apply.")
    )

    assert detection.opt_cpt_flag is True
    assert detection.requires_llm_review is False
    assert detection.matched_signals


def test_detects_explicit_sponsorship_available_language():
    detection = detect_work_authorization(
        _job("Visa sponsorship is available for qualified applicants.")
    )

    assert detection.opt_cpt_flag is True
    assert "sponsorship available" in detection.matched_signals


def test_detects_no_sponsorship_language_as_not_friendly():
    detection = detect_work_authorization(
        _job("Applicants must be authorized to work in the U.S. without sponsorship.")
    )

    assert detection.opt_cpt_flag is False
    assert detection.requires_llm_review is False
    assert detection.matched_signals


def test_marks_broad_work_authorization_language_for_llm_review():
    detection = detect_work_authorization(
        _job("Candidates will answer standard work authorization questions.")
    )

    assert detection.opt_cpt_flag is None
    assert detection.requires_llm_review is True
    assert "mentions work authorization" in detection.matched_signals


def test_no_work_authorization_language_stays_unknown_without_llm_review():
    detection = detect_work_authorization(
        _job("Build SQL dashboards and partner with product teams.")
    )

    assert detection.opt_cpt_flag is None
    assert detection.requires_llm_review is False
    assert detection.matched_signals == []


def test_decisive_rules_do_not_call_llm_classifier():
    def fail_if_called(*_args):
        raise AssertionError("LLM classifier should only run for ambiguous cases")

    detection = detect_work_authorization(
        _job("Candidates using OPT are welcome."),
        llm_classifier=fail_if_called,
    )

    assert detection.opt_cpt_flag is True


def test_ambiguous_rules_can_use_llm_classifier_fallback():
    calls = []

    def classify_with_llm(job, detection):
        calls.append((job, detection))
        return False

    detection = detect_work_authorization(
        _job("Candidates will answer standard work authorization questions."),
        llm_classifier=classify_with_llm,
    )

    assert detection.opt_cpt_flag is False
    assert detection.requires_llm_review is False
    assert detection.reason == (
        "Ambiguous work authorization language classified by LLM fallback."
    )
    assert len(calls) == 1

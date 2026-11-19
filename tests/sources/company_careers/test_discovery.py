"""Discovery tests using minimal saved HTML snippets per ATS platform."""

from hope_job_agent.sources.company_careers.discovery import detect_ats_candidates


def _single_supported(html: str):
    result = detect_ats_candidates(html)
    assert len(result.supported) >= 1
    return result.supported[0]


def test_detects_greenhouse_boards_api():
    candidate = _single_supported(
        '<script src="https://boards-api.greenhouse.io/v1/boards/stripe/jobs">'
    )
    assert candidate.provider == "greenhouse"
    assert candidate.slug == "stripe"


def test_detects_greenhouse_embed():
    candidate = _single_supported(
        '<iframe src="https://boards.greenhouse.io/embed/job_board?for=databricks">'
    )
    assert candidate.provider == "greenhouse"
    assert candidate.slug == "databricks"


def test_detects_lever():
    candidate = _single_supported('<a href="https://jobs.lever.co/palantir">Jobs</a>')
    assert candidate.provider == "lever"
    assert candidate.slug == "palantir"


def test_detects_ashby():
    candidate = _single_supported(
        'fetch("https://api.ashbyhq.com/posting-api/job-board/openai")'
    )
    assert candidate.provider == "ashby"
    assert candidate.slug == "openai"


def test_detects_smartrecruiters():
    candidate = _single_supported(
        '<a href="https://jobs.smartrecruiters.com/ServiceNow">See all jobs</a>'
    )
    assert candidate.provider == "smartrecruiters"
    assert candidate.slug == "ServiceNow"


def test_detects_workday_with_locale_path():
    candidate = _single_supported(
        '<a href="https://cognizant.wd3.myworkdayjobs.com/en-US/CognizantCareers/'
        'job/Teaneck/Analyst_12345">Apply</a>'
    )
    assert candidate.provider == "workday"
    assert candidate.host == "cognizant.wd3.myworkdayjobs.com"
    assert candidate.site == "CognizantCareers"


def test_detects_workday_cxs_endpoint():
    candidate = _single_supported(
        "https://acme.wd12.myworkdayjobs.com/wday/cxs/acme/External_Career_Site/jobs"
    )
    assert candidate.provider == "workday"
    assert candidate.tenant == "acme"
    assert candidate.site == "External_Career_Site"


def test_phenom_page_with_workday_apply_link_resolves_to_workday():
    html = (
        '<script src="https://widget.phenompeople.com/widget.js"></script>'
        '<a href="https://elevancehealth.wd1.myworkdayjobs.com/en-US/ANT/job/'
        'Indianapolis/Business-Analyst_JR100">Apply on Workday</a>'
    )
    result = detect_ats_candidates(html)
    providers = {c.provider for c in result.supported}
    assert "workday" in providers
    assert "phenom" in result.unsupported_markers


def test_detects_oraclecloud_candidate_experience():
    candidate = _single_supported(
        '<a href="https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/'
        'en/sites/CX_45001/job/276708">Analyst</a>'
    )
    assert candidate.provider == "oraclecloud"
    assert candidate.host == "eeho.fa.us2.oraclecloud.com"
    assert candidate.site == "CX_45001"


def test_unsupported_markers_reported():
    html = (
        '<a href="https://careers-acme.icims.com/jobs">iCIMS</a>'
        '<a href="https://jobs.sap.com/">SF</a>'
        '<a href="https://acme.taleo.net/careersection/ex/jobsearch.ftl">Taleo</a>'
        '<a href="https://acme.avature.net/careers">Avature</a>'
    )
    result = detect_ats_candidates(html)
    assert result.supported == []
    assert set(result.unsupported_markers) == {
        "icims",
        "successfactors",
        "taleo",
        "avature",
    }


def test_empty_html_yields_no_candidates():
    result = detect_ats_candidates("")
    assert result.candidates == []

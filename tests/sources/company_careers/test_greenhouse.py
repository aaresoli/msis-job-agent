from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.providers.greenhouse import (
    GreenhouseProvider,
)

from .conftest import load_fixture, make_client


def _target() -> CompanyTarget:
    return CompanyTarget(
        company_name="Acme", ats_provider="greenhouse", ats_slug="acme"
    )


def test_greenhouse_parses_jobs(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    provider = GreenhouseProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    assert len(jobs) == 3
    analyst = jobs[0]
    assert analyst.title == "Data Analyst Intern"
    assert analyst.source_job_id == "1001"
    assert analyst.company == "Acme"
    assert analyst.url == "https://boards.greenhouse.io/acme/jobs/1001"
    assert analyst.department == "Data & Analytics"
    assert "Tableau" in analyst.description  # HTML entities decoded
    assert analyst.posted_date is not None


def test_greenhouse_marks_remote_location_type(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    provider = GreenhouseProvider()

    jobs = provider.fetch(make_client(transport), _target(), FetchPolicy())

    remote_job = next(job for job in jobs if job.source_job_id == "1002")
    assert remote_job.location_type == "remote"


def test_greenhouse_respects_max_jobs_per_company(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body=load_fixture("greenhouse_jobs.json"),
    )
    provider = GreenhouseProvider()

    jobs = provider.fetch(
        make_client(transport), _target(), FetchPolicy(max_jobs_per_company=1)
    )

    assert len(jobs) == 1


def test_entity_encoded_html_is_reduced_to_plain_text():
    """Greenhouse returns HTML that is itself entity-encoded.

    Stripping tags once found nothing to strip (there were no literal ``<``),
    and the unescape that followed turned the entities back into markup that
    nothing removed. Every Greenhouse posting in a real sweep reached the
    database with its tags intact -- which broke the enrichment contract,
    because the model quotes the rendered salary while the stored text still
    held the surrounding spans.
    """

    from hope_job_agent.sources.company_careers.providers.base import clean_html

    raw = (
        "Pay Range</div>&lt;div class=&quot;pay-range&quot;&gt;"
        "&lt;span&gt;$269,800&lt;/span&gt;"
        "&lt;span class=&quot;divider&quot;&gt;&amp;mdash;&lt;/span&gt;"
        "&lt;span&gt;$370,900 USD&lt;/span&gt;&lt;/div&gt;"
    )

    cleaned = clean_html(raw)

    assert "<" not in cleaned
    assert "&mdash;" not in cleaned
    # The exact string the model quotes has to be findable in the stored text,
    # or _unsupported_quotes rejects a perfectly good extraction.
    assert "$269,800 — $370,900 USD" in cleaned


def test_plain_html_is_still_handled():
    from hope_job_agent.sources.company_careers.providers.base import clean_html

    assert clean_html("<p>Hello<br/>world</p> &amp; more") == "Hello world & more"
    assert clean_html(None) == ""

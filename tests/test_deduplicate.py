from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.deduplicate import canonicalize_url, deduplicate_jobs


def _job(url: str, title: str = "Data Analyst Intern") -> JobPosting:
    return JobPosting(
        source="employer_careers",
        title=title,
        company="Example Employer",
        location="Bloomington, IN",
        description="Analyze business data with SQL and Python.",
        url=url,
    )


def test_deduplicate_jobs_removes_duplicate_urls():
    jobs = [
        _job("https://example.com/jobs/1"),
        _job("https://example.com/jobs/1/", title="Duplicate Posting"),
        _job("https://example.com/jobs/2", title="Security Analyst Intern"),
    ]

    deduplicated = deduplicate_jobs(jobs)

    assert len(deduplicated) == 2
    assert deduplicated[0].title == "Data Analyst Intern"
    assert deduplicated[1].title == "Security Analyst Intern"


def test_canonicalize_url_removes_tracking_params():
    assert (
        canonicalize_url("HTTPS://Example.com/jobs/1/?utm_source=email&keep=yes")
        == "https://example.com/jobs/1?keep=yes"
    )


def test_deduplicate_jobs_keeps_distinct_roles_with_same_attributes():
    jobs = [
        _job("https://example.com/jobs/1", title="Systems Analyst"),
        _job("https://example.com/jobs/2", title="Systems Analyst"),
    ]
    jobs[1] = jobs[1].model_copy(update={"description": "Configure ERP workflows."})

    deduplicated = deduplicate_jobs(jobs)

    assert len(deduplicated) == 2

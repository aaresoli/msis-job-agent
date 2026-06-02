from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.runner import run_pipeline
from hope_job_agent.sources.base import BaseJobSource


class FakeJobSource(BaseJobSource):
    source_name = "fake_source"

    def __init__(self, jobs: list[JobPosting]) -> None:
        self._jobs = jobs

    def fetch_jobs(self) -> list[JobPosting]:
        return self._jobs

    def health_check(self) -> bool:
        return True


def _job(
    url: str,
    title: str = "Data Analyst Intern",
    company: str = "Example Analytics",
    tags: list[str] | None = None,
) -> JobPosting:
    return JobPosting(
        source="approved_test_export",
        title=title,
        company=company,
        location=" Bloomington, IN ",
        description=" Analyze data with SQL and Python. ",
        url=url,
        concentration_tags=tags or ["Business Analytics", "Unknown Track"],
    )


def test_run_pipeline_normalizes_validates_classifies_and_deduplicates():
    jobs = [
        _job("https://example.com/jobs/1", title=" Data Analyst Intern "),
        _job("https://example.com/jobs/1/", title="Duplicate Data Analyst Intern"),
        _job("https://example.com/jobs/2", title=" Security Analyst Intern "),
        _job("https://example.com/jobs/3", company=" "),
    ]

    result = run_pipeline([FakeJobSource(jobs)])

    assert result.raw_count == 4
    assert result.valid_count == 3
    assert result.invalid_count == 1
    assert result.deduplicated_count == 2
    assert len(result.final_jobs) == 2
    assert result.final_jobs[0].title == "Data Analyst Intern"
    assert result.final_jobs[0].location == "Bloomington, IN"
    assert result.final_jobs[0].description == "Analyze data with SQL and Python."
    assert result.final_jobs[0].concentration_tags == ["Business Analytics"]

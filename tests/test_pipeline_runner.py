from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.runner import run_pipeline
from hope_job_agent.sources.base import BaseJobSource


class FakeJobSource(BaseJobSource):
    source_name = "employer_careers"

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


def test_run_pipeline_normalizes_validates_classifies_and_deduplicates(tmp_path):
    jobs = [
        _job("https://example.com/jobs/1", title=" Data Analyst Intern "),
        _job("https://example.com/jobs/1/", title="Duplicate Data Analyst Intern"),
        _job("https://example.com/jobs/2", title=" Security Analyst Intern "),
        JobPosting.model_construct(
            source="employer_careers",
            title="Invalid Job",
            company=" ",
            location="Bloomington, IN",
            description="Missing company after normalization.",
            url="https://example.com/jobs/3",
            concentration_tags=[],
            role_tags=[],
        ),
    ]

    result = run_pipeline(
        [FakeJobSource(jobs)],
        output_path=tmp_path / "pipeline_results.json",
        database_url=f"sqlite:///{(tmp_path / 'pipeline.sqlite3').as_posix()}",
    )

    assert result.raw_count == 4
    assert result.valid_count == 3
    assert result.invalid_count == 1
    assert result.deduplicated_count == 2
    assert len(result.final_jobs) == 2
    assert result.final_jobs[0].title == "Data Analyst Intern"
    assert result.final_jobs[0].location == "Bloomington, IN"
    assert result.final_jobs[0].description == "Analyze data with SQL and Python."
    assert result.final_jobs[0].role_tags == ["Data Analyst / BI Engineer"]
    assert result.final_jobs[0].concentration_tags == [
        "Data Analytics and AI",
        "Information Systems Research in AI",
    ]

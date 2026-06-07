from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.employer_careers import EmployerCareersSource


def test_employer_careers_source_returns_sample_job_postings():
    source = EmployerCareersSource()

    jobs = source.fetch_jobs()

    assert source.health_check() is True
    assert jobs
    assert all(isinstance(job, JobPosting) for job in jobs)
    assert all(job.source == "employer_careers" for job in jobs)

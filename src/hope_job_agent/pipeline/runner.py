"""Thin-slice pipeline runner for approved job sources."""

from collections.abc import Sequence
from dataclasses import dataclass

from hope_job_agent.classification.classifier import classify_job
from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.pipeline.ingest import ingest_jobs
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.pipeline.validate import validate_job
from hope_job_agent.sources.base import BaseJobSource


@dataclass(frozen=True)
class PipelineRunResult:
    """Counts and output from one pipeline run."""

    raw_count: int
    valid_count: int
    invalid_count: int
    deduplicated_count: int
    final_jobs: list[JobPosting]


def run_pipeline(sources: Sequence[BaseJobSource]) -> PipelineRunResult:
    """Run the v0 ingest, normalize, validate, classify, and deduplicate slice."""

    raw_jobs: list[JobPosting] = []
    for source in sources:
        raw_jobs.extend(ingest_jobs(source))

    valid_jobs: list[JobPosting] = []
    invalid_count = 0

    for raw_job in raw_jobs:
        normalized_job = normalize_job(raw_job)
        if not validate_job(normalized_job):
            invalid_count += 1
            continue

        valid_jobs.append(
            normalized_job.model_copy(
                update={"concentration_tags": classify_job(normalized_job)}
            )
        )

    final_jobs = deduplicate_jobs(valid_jobs)
    return PipelineRunResult(
        raw_count=len(raw_jobs),
        valid_count=len(valid_jobs),
        invalid_count=invalid_count,
        deduplicated_count=len(final_jobs),
        final_jobs=final_jobs,
    )

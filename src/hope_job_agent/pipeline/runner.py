"""Thin-slice pipeline runner for approved job sources."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.pipeline.ingest import ingest_jobs
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.pipeline.validate import validate_job
from hope_job_agent.scoring.ranker import rank_jobs_for_student
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.registry import ensure_source_allowed
from hope_job_agent.utils.output import write_pipeline_output


@dataclass(frozen=True)
class PipelineRunResult:
    """Counts and output from one pipeline run."""

    raw_count: int
    valid_count: int
    invalid_count: int
    deduplicated_count: int
    final_jobs: list[JobPosting]
    ranked_matches: dict[str, list[JobMatch]]
    output_path: Path


def run_pipeline(
    sources: Sequence[BaseJobSource],
    student_profiles: Sequence[StudentProfile] | None = None,
    output_path: Path | str = Path("data/output/pipeline_results.json"),
) -> PipelineRunResult:
    """Run the v0 ingest, normalize, validate, classify, deduplicate, rank slice."""

    raw_jobs: list[JobPosting] = []
    for source in sources:
        ensure_source_allowed(source.source_name)
        raw_jobs.extend(ingest_jobs(source))

    valid_jobs: list[JobPosting] = []
    invalid_count = 0

    for raw_job in raw_jobs:
        normalized_job = normalize_job(raw_job)
        if not validate_job(normalized_job):
            invalid_count += 1
            continue

        valid_jobs.append(classify_job_posting(normalized_job))

    final_jobs = deduplicate_jobs(valid_jobs)
    ranked_matches = {
        profile.name: rank_jobs_for_student(profile, final_jobs)
        for profile in student_profiles or []
        if profile.ai_matching_consent
    }
    resolved_output_path = Path(output_path)
    write_pipeline_output(
        output_path=resolved_output_path,
        raw_count=len(raw_jobs),
        valid_count=len(valid_jobs),
        invalid_count=invalid_count,
        final_jobs=final_jobs,
        ranked_matches=ranked_matches,
    )
    return PipelineRunResult(
        raw_count=len(raw_jobs),
        valid_count=len(valid_jobs),
        invalid_count=invalid_count,
        deduplicated_count=len(final_jobs),
        final_jobs=final_jobs,
        ranked_matches=ranked_matches,
        output_path=resolved_output_path,
    )

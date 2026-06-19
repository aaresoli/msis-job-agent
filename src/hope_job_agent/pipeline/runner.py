"""Thin-slice pipeline runner for approved job sources."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.config import get_settings
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
from hope_job_agent.storage import SQLiteJobStore
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
    database_url: str | None = None,
) -> PipelineRunResult:
    """Run the v0 ingest, normalize, validate, classify, deduplicate, rank slice."""

    raw_jobs: list[JobPosting] = []
    for source in sources:
        ensure_source_allowed(source.source_name)
        raw_jobs.extend(ingest_jobs(source))

    normalized_jobs: list[JobPosting] = []
    valid_jobs: list[JobPosting] = []
    invalid_count = 0

    for raw_job in raw_jobs:
        normalized_job = normalize_job(raw_job)
        normalized_jobs.append(normalized_job)
        if not validate_job(normalized_job):
            invalid_count += 1
            continue

        valid_jobs.append(classify_job_posting(normalized_job))

    final_jobs = deduplicate_jobs(valid_jobs)
    active_profiles = [
        profile for profile in student_profiles or [] if profile.ai_matching_consent
    ]
    ranked_profile_matches = [
        (profile, rank_jobs_for_student(profile, final_jobs))
        for profile in active_profiles
    ]
    ranked_matches = {
        profile.name: matches for profile, matches in ranked_profile_matches
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
    run_id = str(uuid4())
    source_label = ", ".join(source.source_name for source in sources)
    summary = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": source_label,
        "output_path": str(resolved_output_path),
        "raw_count": len(raw_jobs),
        "normalized_count": len(normalized_jobs),
        "valid_count": len(valid_jobs),
        "invalid_count": invalid_count,
        "duplicate_count": len(valid_jobs) - len(final_jobs),
        "unique_count": len(final_jobs),
        "classified_count": len(final_jobs),
        "profile_count": len(student_profiles or []),
        "active_profile_count": len(active_profiles),
        "total_ranked_matches": sum(
            len(matches) for _profile, matches in ranked_profile_matches
        ),
        "warnings": [],
        "errors": [],
    }
    resolved_database_url = (
        database_url
        if database_url is not None
        else get_settings().database_url.get_secret_value()
    )
    store = SQLiteJobStore(resolved_database_url)
    try:
        store.persist_pipeline_run(
            run_id=run_id,
            run_type="thin",
            source=source_label,
            summary=summary,
            normalized_jobs=normalized_jobs,
            valid_jobs=valid_jobs,
            deduped_jobs=final_jobs,
            ranked_matches=ranked_profile_matches,
            output_path=resolved_output_path,
        )
    finally:
        store.close()

    return PipelineRunResult(
        raw_count=len(raw_jobs),
        valid_count=len(valid_jobs),
        invalid_count=invalid_count,
        deduplicated_count=len(final_jobs),
        final_jobs=final_jobs,
        ranked_matches=ranked_matches,
        output_path=resolved_output_path,
    )

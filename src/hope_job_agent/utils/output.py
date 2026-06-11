"""JSON output helpers for local pipeline reports."""

import json
from pathlib import Path

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch


def write_pipeline_output(
    output_path: Path,
    raw_count: int,
    valid_count: int,
    invalid_count: int,
    final_jobs: list[JobPosting],
    ranked_matches: dict[str, list[JobMatch]],
) -> None:
    """Write a predictable JSON report for teammate smoke tests."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "raw_jobs": raw_count,
            "valid_jobs": valid_count,
            "invalid_jobs": invalid_count,
            "deduplicated_jobs": len(final_jobs),
        },
        "jobs": [job.model_dump(mode="json") for job in final_jobs],
        "ranked_matches": {
            student_name: [match.model_dump(mode="json") for match in matches]
            for student_name, matches in ranked_matches.items()
        },
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

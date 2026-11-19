"""In-memory JobStore for dry-run and unit tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile


@dataclass
class MemoryJobStore:
    """Non-persistent store that records pipeline runs in memory."""

    database_url: str = "memory://"
    runs: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[JobPosting] = field(default_factory=list)
    closed: bool = False

    def preflight(self) -> None:
        return None

    def persist_pipeline_run(
        self,
        *,
        run_id: str,
        run_type: str,
        source: str,
        summary: Mapping[str, Any],
        normalized_jobs: Sequence[JobPosting],
        valid_jobs: Sequence[JobPosting],
        deduped_jobs: Sequence[JobPosting],
        ranked_matches: Sequence[tuple[StudentProfile, Sequence[JobMatch]]],
        input_path: Path | str | None = None,
        profiles_path: Path | str | None = None,
        output_path: Path | str | None = None,
    ) -> None:
        self.runs.append(
            {
                "run_id": run_id,
                "run_type": run_type,
                "source": source,
                "summary": dict(summary),
                "normalized_count": len(normalized_jobs),
                "valid_count": len(valid_jobs),
                "deduped_count": len(deduped_jobs),
                "ranked_profiles": len(ranked_matches),
                "input_path": None if input_path is None else str(input_path),
                "profiles_path": None if profiles_path is None else str(profiles_path),
                "output_path": None if output_path is None else str(output_path),
            }
        )
        self.jobs = list(deduped_jobs)

    def table_counts(self, *table_names: str) -> dict[str, int]:
        mapping = {
            "source_runs": len(self.runs),
            "job_postings": len(self.jobs),
            "pipeline_runs": len(self.runs),
        }
        return {name: mapping.get(name, 0) for name in table_names}

    def close(self) -> None:
        self.closed = True

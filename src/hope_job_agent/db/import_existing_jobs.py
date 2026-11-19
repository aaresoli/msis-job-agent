"""Import local JSON/CSV job exports into PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.config.database import resolve_database_url
from hope_job_agent.db.session import (
    create_db_engine,
    create_session_factory,
    session_scope,
)
from hope_job_agent.models.job import JobPosting
from hope_job_agent.persistence.job_repository import JobPostingRepository
from hope_job_agent.persistence.source_run_repository import SourceRunRepository
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.pipeline.validate import validate_job
from hope_job_agent.sources.registry import create_source_adapter


def import_jobs_from_file(
    input_path: Path,
    *,
    source_name: str,
    database_url: str | None = None,
    dry_run: bool = False,
) -> dict[str, int | list[str]]:
    """Load, normalize, dedupe, and upsert jobs from a local export file."""

    adapter = create_source_adapter(source_name, input_path)
    if hasattr(adapter, "fetch_jobs_with_warnings"):
        result = adapter.fetch_jobs_with_warnings()
        jobs = list(result.jobs)
    else:
        jobs = adapter.fetch_jobs()

    normalized = [normalize_job(job) for job in jobs]
    valid = [job for job in normalized if validate_job(job)]
    unique = deduplicate_jobs(valid)
    classified = [classify_job_posting(job) for job in unique]

    if dry_run:
        return {
            "inserted": 0,
            "updated": 0,
            "skipped": len(classified),
            "errors": [],
            "loaded": len(jobs),
            "valid": len(valid),
            "unique": len(unique),
        }

    url = resolve_database_url(database_url, storage="postgres")
    engine = create_db_engine(url, storage="postgres")
    session_factory = create_session_factory(engine)

    with session_scope(session_factory) as session:
        runs = SourceRunRepository(session)
        jobs_repo = JobPostingRepository(session)
        run = runs.start_run(
            source_name,
            metadata={"import_path": str(input_path), "full_refresh": False},
        )
        summary = jobs_repo.upsert_many(classified, source_run_id=run.id)
        runs.finish_run(
            run.id,
            summary={
                "raw_count": len(jobs),
                "jobs_inserted": summary.inserted,
                "jobs_updated": summary.updated,
                "jobs_skipped": summary.skipped,
                "duplicate_count": len(valid) - len(unique),
                "errors": summary.errors,
            },
        )

    engine.dispose()
    return {
        "inserted": summary.inserted,
        "updated": summary.updated,
        "skipped": summary.skipped,
        "errors": summary.errors,
        "loaded": len(jobs),
        "valid": len(valid),
        "unique": len(unique),
    }


def _load_jobs_from_json(path: Path) -> list[JobPosting]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Input JSON must be a list or {jobs: [...]} object")
    jobs: list[JobPosting] = []
    for index, record in enumerate(records, start=1):
        try:
            jobs.append(JobPosting.model_validate(record))
        except ValidationError as exc:
            raise ValueError(f"Invalid job at index {index}: {exc}") from exc
    return jobs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hope_job_agent.db.import_existing_jobs",
        description="Import a local job export into PostgreSQL.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Input file path.")
    parser.add_argument(
        "--source",
        default="kelleylink_excel",
        help="Source adapter name (kelleylink_excel, ksbit_export, approved_json).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL DATABASE_URL. Defaults to env DATABASE_URL / POSTGRES_*.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and dedupe without writing to PostgreSQL.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        raise SystemExit(1)
    try:
        summary = import_jobs_from_file(
            args.input,
            source_name=args.source,
            database_url=args.database_url,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Import failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("Import complete")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

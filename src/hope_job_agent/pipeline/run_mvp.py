"""MVP end-to-end pipeline runner for approved local job exports."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.config import get_settings
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.pipeline.validate import validate_job
from hope_job_agent.scoring.ranker import rank_jobs_for_student
from hope_job_agent.sources.approved_json import (
    ApprovedJsonJobSource,
    ApprovedJsonSourceError,
)
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.ksbit_export import (
    KsbitExportSource,
    KsbitExportSourceError,
)
from hope_job_agent.sources.registry import SourceComplianceError, ensure_source_allowed
from hope_job_agent.utils.hashing import stable_hash
from hope_job_agent.utils.logging import configure_logging

LOGGER = logging.getLogger(__name__)

MVP_OUTPUT_COLUMNS = [
    "student_id",
    "student_name",
    "title",
    "company",
    "location",
    "source",
    "apply_url/post_url",
    "role_category",
    "target_role",
    "concentration_tags",
    "seniority_level",
    "opt_cpt_flag",
    "final_score",
    "score_breakdown",
    "ranking_explanation",
]


class MvpPipelineError(RuntimeError):
    """Raised when the MVP pipeline cannot safely complete."""


@dataclass(frozen=True)
class SourceLoadResult:
    """Raw jobs loaded from one approved source."""

    source: BaseJobSource
    jobs: list[JobPosting]
    raw_count: int
    warnings: list[str]


@dataclass(frozen=True)
class MvpPipelineResult:
    """MVP pipeline outputs and summary data."""

    output_path: Path
    summary_path: Path
    rows: list[dict[str, Any]]
    summary: dict[str, Any]


def run_mvp_pipeline(
    *,
    source_name: str,
    input_path: Path,
    profiles_path: Path,
    output_path: Path,
    limit: int | None = None,
    source_since_date: str | None = None,
    source_limit: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> MvpPipelineResult:
    """Run the approved-source MVP pipeline end to end."""

    started_at = perf_counter()
    settings = get_settings()
    configure_logging("DEBUG" if verbose else settings.log_level)
    warnings: list[str] = []

    LOGGER.info("Loading MVP pipeline configuration")
    if limit is not None and limit < 1:
        raise MvpPipelineError("--limit must be a positive integer")

    source_load = _load_source(
        source_name=source_name,
        input_path=input_path,
        source_since_date=source_since_date,
        source_limit=source_limit,
    )
    warnings.extend(source_load.warnings)
    _log_warnings(source_load.warnings)

    if source_load.raw_count == 0:
        raise MvpPipelineError(f"Input file contains no job records: {input_path}")
    if not source_load.jobs:
        raise MvpPipelineError(
            f"No usable jobs found in input after validation: {input_path}"
        )

    normalized_jobs = _normalize_jobs(source_load.jobs, warnings)
    valid_jobs = _validate_jobs(normalized_jobs, warnings)
    if not valid_jobs:
        raise MvpPipelineError("No valid jobs remained after normalization")

    unique_jobs = deduplicate_jobs(valid_jobs)
    duplicate_count = len(valid_jobs) - len(unique_jobs)
    classified_jobs = _classify_jobs(unique_jobs, warnings)

    profiles = _load_student_profiles(profiles_path)
    ranked_rows = _rank_jobs_for_profiles(
        profiles=profiles,
        jobs=classified_jobs,
        limit=limit,
        warnings=warnings,
    )
    ranked_rows.sort(
        key=lambda row: (
            str(row["student_id"]),
            -float(row["final_score"]),
            str(row["company"]),
            str(row["title"]),
        )
    )

    if dry_run:
        warnings.append("Dry run requested; output files were not written.")
        LOGGER.info("Dry run requested; skipping output writes")
    else:
        _write_results(output_path, ranked_rows)

    summary_path = _summary_path_for(output_path)
    summary = {
        "run_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "source": source_name,
        "source_since_date": source_since_date,
        "source_limit": source_limit,
        "input_path": str(input_path),
        "profiles_path": str(profiles_path),
        "output_path": str(output_path),
        "raw_count": source_load.raw_count,
        "normalized_count": len(normalized_jobs),
        "invalid_count": len(normalized_jobs) - len(valid_jobs),
        "duplicate_count": duplicate_count,
        "unique_count": len(unique_jobs),
        "classified_count": len(classified_jobs),
        "profile_count": len(profiles),
        "active_profile_count": sum(
            1 for profile in profiles if profile.ai_matching_consent
        ),
        "total_ranked_matches": len(ranked_rows),
        "warnings": warnings,
        "errors": [],
        "runtime_seconds": round(perf_counter() - started_at, 3),
    }

    if not dry_run:
        _write_summary(summary_path, summary)

    return MvpPipelineResult(
        output_path=output_path,
        summary_path=summary_path,
        rows=ranked_rows,
        summary=summary,
    )


def _load_source(
    source_name: str,
    input_path: Path,
    source_since_date: str | None = None,
    source_limit: int | None = None,
) -> SourceLoadResult:
    """Load jobs from an approved local source adapter."""

    _require_file(input_path, "Input file")
    try:
        ensure_source_allowed(source_name)
    except SourceComplianceError as exc:
        raise MvpPipelineError(str(exc)) from exc

    LOGGER.info("Loading source adapter: %s", source_name)
    if source_name == "approved_json":
        if source_since_date is not None or source_limit is not None:
            raise MvpPipelineError(
                "--source-since-date and --source-limit are only supported for "
                "ksbit_export"
            )
        approved_source = ApprovedJsonJobSource(input_path)
        try:
            approved_result = approved_source.fetch_jobs_with_warnings()
        except ApprovedJsonSourceError as exc:
            raise MvpPipelineError(str(exc)) from exc
        return SourceLoadResult(
            source=approved_source,
            jobs=approved_result.jobs,
            raw_count=approved_result.raw_count,
            warnings=approved_result.warnings,
        )

    if source_name == "ksbit_export":
        try:
            ksbit_source = KsbitExportSource(
                input_path,
                since_date=source_since_date,
                limit=source_limit,
            )
            ksbit_result = ksbit_source.fetch_jobs_with_warnings()
        except KsbitExportSourceError as exc:
            raise MvpPipelineError(str(exc)) from exc
        return SourceLoadResult(
            source=ksbit_source,
            jobs=ksbit_result.jobs,
            raw_count=ksbit_result.raw_count,
            warnings=ksbit_result.warnings,
        )

    raise MvpPipelineError(
        "MVP runner v1 supports --source approved_json or --source ksbit_export"
    )


def _normalize_jobs(
    jobs: Sequence[JobPosting],
    warnings: list[str],
) -> list[JobPosting]:
    """Normalize jobs while warning on recoverable record failures."""

    normalized_jobs: list[JobPosting] = []
    LOGGER.info("Normalizing %s jobs", len(jobs))
    for index, job in enumerate(jobs, start=1):
        try:
            normalized_jobs.append(normalize_job(job))
        except (AttributeError, TypeError, ValueError) as exc:
            warning = f"Skipped job {index} during normalization: {exc}"
            warnings.append(warning)
            LOGGER.warning(warning)
    return normalized_jobs


def _validate_jobs(
    jobs: Sequence[JobPosting],
    warnings: list[str],
) -> list[JobPosting]:
    """Keep jobs with the minimum fields required downstream."""

    valid_jobs: list[JobPosting] = []
    LOGGER.info("Validating %s normalized jobs", len(jobs))
    for index, job in enumerate(jobs, start=1):
        if validate_job(job):
            valid_jobs.append(job)
            continue

        warning = (
            "Skipped invalid job "
            f"{index} after normalization: missing required source, title, "
            "company, location, description, or URL"
        )
        warnings.append(warning)
        LOGGER.warning(warning)
    return valid_jobs


def _classify_jobs(
    jobs: Sequence[JobPosting],
    warnings: list[str],
) -> list[JobPosting]:
    """Classify unique jobs with the existing deterministic classifier."""

    classified_jobs: list[JobPosting] = []
    LOGGER.info("Classifying %s unique jobs", len(jobs))
    for index, job in enumerate(jobs, start=1):
        try:
            classified_jobs.append(classify_job_posting(job))
        except (AttributeError, TypeError, ValueError) as exc:
            warning = (
                f"Classifier failed for job {index}; "
                f"exporting unclassified job: {exc}"
            )
            warnings.append(warning)
            LOGGER.warning(warning)
            # TODO(MSI-22): Add a pluggable keyword fallback if classifier rules move.
            classified_jobs.append(job)
    return classified_jobs


def _load_student_profiles(profiles_path: Path) -> list[StudentProfile]:
    """Load student profiles from a local JSON list or {profiles: [...]} file."""

    _require_file(profiles_path, "Profiles file")
    try:
        payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MvpPipelineError(
            f"Profiles file is not valid JSON: {profiles_path}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise MvpPipelineError(
            f"Profiles file could not be read: {profiles_path}: {exc}"
        ) from exc

    records = payload.get("profiles") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise MvpPipelineError(
            "Profiles file must be a JSON array or an object with a profiles array"
        )
    if not records:
        raise MvpPipelineError(f"Profiles file is empty: {profiles_path}")

    profiles: list[StudentProfile] = []
    for index, record in enumerate(records, start=1):
        try:
            profiles.append(StudentProfile.model_validate(record))
        except ValidationError as exc:
            raise MvpPipelineError(
                "Profiles file contains an invalid profile "
                f"at index {index}: {_summarize_validation_error(exc)}"
            ) from exc

    return profiles


def _rank_jobs_for_profiles(
    *,
    profiles: Sequence[StudentProfile],
    jobs: Sequence[JobPosting],
    limit: int | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Rank jobs for every consenting profile and return flat export rows."""

    rows: list[dict[str, Any]] = []
    LOGGER.info("Ranking %s jobs for %s profiles", len(jobs), len(profiles))

    for profile in profiles:
        if not profile.ai_matching_consent:
            warning = f"Skipped profile without AI matching consent: {profile.name}"
            warnings.append(warning)
            LOGGER.warning(warning)
            continue

        matches = rank_jobs_for_student(profile, list(jobs))
        if limit is not None:
            matches = matches[:limit]
        rows.extend(_match_to_row(profile, match) for match in matches)

    return rows


def _match_to_row(profile: StudentProfile, match: JobMatch) -> dict[str, Any]:
    """Convert one ranked match into the documented MVP export fields."""

    job = match.job
    reasons = match.reasons
    score_breakdown = {
        "reasons": reasons,
        "metadata": match.metadata,
    }
    return {
        "student_id": _student_id(profile),
        "student_name": profile.name,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source": job.source,
        "apply_url/post_url": job.url,
        "role_category": "; ".join(job.role_tags),
        "target_role": "; ".join(profile.target_roles),
        "concentration_tags": "; ".join(job.concentration_tags),
        "seniority_level": match.metadata.get("seniority") or job.seniority or "",
        "opt_cpt_flag": job.opt_cpt_flag,
        "final_score": round(match.score, 4),
        "score_breakdown": json.dumps(score_breakdown, sort_keys=True),
        "ranking_explanation": (
            "; ".join(reasons) if reasons else "No deterministic match signals found"
        ),
    }


def _student_id(profile: StudentProfile) -> str:
    if profile.student_id and profile.student_id.strip():
        return profile.student_id.strip()
    return stable_hash(profile.name)[:10]


def _write_results(output_path: Path, rows: list[dict[str, Any]]) -> None:
    """Write MVP results to CSV by default, or JSON for .json outputs."""

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.casefold() == ".json":
            output_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            return

        with output_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=MVP_OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        raise MvpPipelineError(
            f"Output path could not be written: {output_path}: {exc}"
        ) from exc


def _write_summary(summary_path: Path, summary: dict[str, Any]) -> None:
    """Write the run summary JSON beside the results file."""

    try:
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except OSError as exc:
        raise MvpPipelineError(
            f"Summary path could not be written: {summary_path}: {exc}"
        ) from exc


def _summary_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.summary.json")


def _require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise MvpPipelineError(f"{label} not found: {path}")
    if not path.is_file():
        raise MvpPipelineError(f"{label} is not a file: {path}")


def _log_warnings(warnings: Sequence[str]) -> None:
    for warning in warnings:
        LOGGER.warning(warning)


def _summarize_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    first_error = errors[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    message = first_error.get("msg", str(exc))
    return f"{location}: {message}" if location else str(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hope_job_agent.pipeline.run_mvp",
        description="Run the MVP job pipeline against an approved local source.",
    )
    parser.add_argument("--source", required=True, help="Approved source adapter name.")
    parser.add_argument("--input", required=True, type=Path, help="Path to job input.")
    parser.add_argument(
        "--profiles",
        required=True,
        type=Path,
        help="Path to student profiles JSON.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Results path.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum jobs to export per consenting student profile.",
    )
    parser.add_argument(
        "--source-since-date",
        default=None,
        help="For ksbit_export, include records posted on or after YYYY-MM-DD.",
    )
    parser.add_argument(
        "--source-limit",
        type=int,
        default=None,
        help="For ksbit_export, maximum source records returned after filtering.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all steps but skip writing result and summary files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point for the MVP runner."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_mvp_pipeline(
            source_name=args.source,
            input_path=args.input,
            profiles_path=args.profiles,
            output_path=args.output,
            limit=args.limit,
            source_since_date=args.source_since_date,
            source_limit=args.source_limit,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    except MvpPipelineError as exc:
        print(f"MVP pipeline failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    summary = result.summary
    print("MVP pipeline run complete")
    print(f"Run ID: {summary['run_id']}")
    print(f"Source: {summary['source']}")
    print(f"Raw jobs: {summary['raw_count']}")
    print(f"Unique jobs: {summary['unique_count']}")
    print(f"Profiles: {summary['profile_count']}")
    print(f"Ranked matches: {summary['total_ranked_matches']}")
    print(f"Output file: {result.output_path}")
    if args.dry_run:
        print("Summary file: not written (--dry-run)")
    else:
        print(f"Summary file: {result.summary_path}")
    if summary["warnings"]:
        print(f"Warnings: {len(summary['warnings'])}")


if __name__ == "__main__":
    main()

"""MVP end-to-end pipeline runner for approved local job exports."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from hope_job_agent.agents.gcs_agent import summarize_jobs_for_gcs
from hope_job_agent.classification.classifier import classify_job_posting
from hope_job_agent.config import get_settings
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.pipeline.data_quality import (
    DataQualityThresholds,
    build_data_quality_report,
    load_data_quality_thresholds,
)
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.pipeline.validate import validate_job
from hope_job_agent.scoring.ranker import rank_jobs_for_student
from hope_job_agent.sources.apify_linkedin import (
    ApifyLinkedInSettings,
    ApifyLinkedInSource,
    ApifyLinkedInSourceError,
)
from hope_job_agent.sources.approved_json import (
    ApprovedJsonJobSource,
    ApprovedJsonSourceError,
)
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.company_careers import CompanyCareersSource
from hope_job_agent.sources.company_careers.config import (
    DEFAULT_CONFIG_PATH as DEFAULT_COMPANY_CONFIG_PATH,
)
from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfigError,
)
from hope_job_agent.sources.ksbit_export import (
    KsbitExportSource,
    KsbitExportSourceError,
)
from hope_job_agent.sources.registry import (
    SourceComplianceError,
    create_source_adapter,
    ensure_source_allowed,
)
from hope_job_agent.storage import (
    JobStore,
    JobStoreError,
    create_job_store,
)
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

JOBS_OUTPUT_COLUMNS = [
    "source",
    "source_job_id",
    "title",
    "company",
    "location",
    "apply_url/post_url",
    "posted_date",
    "employment_type",
    "seniority",
    "role_tags",
    "concentration_tags",
    "opt_cpt_flag",
    "classification_uncertain",
    "retrieved_at",
]


class MvpPipelineError(RuntimeError):
    """Raised when the MVP pipeline cannot safely complete."""


@dataclass(frozen=True)
class SourceLoadResult:
    """Raw jobs loaded from one or more approved sources."""

    source: BaseJobSource | None
    jobs: list[JobPosting]
    raw_count: int
    warnings: list[str]
    company_health: dict[str, Any] | None = None
    apify_health: dict[str, Any] | None = None


@dataclass(frozen=True)
class MvpPipelineResult:
    """MVP pipeline outputs and summary data."""

    output_path: Path
    summary_path: Path
    rows: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass(frozen=True)
class RankedProfileMatches:
    """Ranked matches for one consenting profile."""

    profile: StudentProfile
    matches: list[JobMatch]


def run_mvp_pipeline(
    *,
    source_name: str,
    input_path: Path | None = None,
    profiles_path: Path | None = None,
    output_path: Path,
    limit: int | None = None,
    source_since_date: str | None = None,
    source_limit: int | None = None,
    company_config_path: Path | None = None,
    local_source: str = "kelleylink_excel",
    company_source: CompanyCareersSource | None = None,
    apify_dataset_id: str | None = None,
    apify_run_id: str | None = None,
    apify_trigger_run: bool = False,
    apify_max_items: int | None = None,
    dry_run: bool = False,
    skip_store: bool = False,
    full_refresh: bool = False,
    verbose: bool = False,
    database_url: str | None = None,
    storage: str = "auto",
    data_quality_thresholds: DataQualityThresholds | None = None,
    store_factory: Callable[[str | None], JobStore] | None = None,
) -> MvpPipelineResult:
    """Run the approved-source MVP pipeline end to end.

    When ``profiles_path`` is omitted the runner operates in jobs-only mode:
    it ingests, normalizes, deduplicates, and classifies postings and writes
    the normalized jobs, a data-quality report, and a GCS trend summary, but
    performs no student ranking.
    """

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
        company_config_path=company_config_path,
        local_source=local_source,
        company_source=company_source,
        apify_dataset_id=apify_dataset_id,
        apify_run_id=apify_run_id,
        apify_trigger_run=apify_trigger_run,
        apify_max_items=apify_max_items,
    )
    warnings.extend(source_load.warnings)
    _log_warnings(source_load.warnings)

    if source_load.raw_count == 0:
        if input_path is not None:
            raise MvpPipelineError(f"Input file contains no job records: {input_path}")
        raise MvpPipelineError(
            f"Source '{source_name}' returned no job records. Check the "
            "company_careers health report for skipped/failed companies."
        )
    if not source_load.jobs:
        raise MvpPipelineError(
            f"No usable jobs found after validation for source '{source_name}'"
        )

    normalized_jobs = _normalize_jobs(source_load.jobs, warnings)
    valid_jobs = _validate_jobs(normalized_jobs, warnings)
    if not valid_jobs:
        raise MvpPipelineError("No valid jobs remained after normalization")

    unique_jobs = deduplicate_jobs(valid_jobs)
    duplicate_count = len(valid_jobs) - len(unique_jobs)
    classified_jobs = _classify_jobs(unique_jobs, warnings)

    profiles: list[StudentProfile] = []
    ranked_profile_matches: list[RankedProfileMatches] = []
    jobs_only = profiles_path is None
    if profiles_path is None:
        LOGGER.info("No profiles provided; running in jobs-only mode")
        warnings.append(
            "No profiles provided; ran jobs-only mode (normalized jobs, "
            "data-quality report, and GCS trends only)."
        )
    else:
        profiles = _load_student_profiles(profiles_path)
        ranked_profile_matches = _rank_jobs_for_profiles(
            profiles=profiles,
            jobs=classified_jobs,
            limit=limit,
            warnings=warnings,
        )

    ranked_rows = [
        _match_to_row(ranked.profile, match)
        for ranked in ranked_profile_matches
        for match in ranked.matches
    ]
    ranked_rows.sort(
        key=lambda row: (
            str(row["student_id"]),
            -float(row["final_score"]),
            str(row["company"]),
            str(row["title"]),
        )
    )

    thresholds = data_quality_thresholds or load_data_quality_thresholds()
    data_quality_report = build_data_quality_report(
        classified_jobs,
        raw_count=source_load.raw_count,
        duplicate_count=duplicate_count,
        adapter_warnings=source_load.warnings,
        short_description_chars=thresholds.short_description_chars,
        stale_after_days=thresholds.stale_after_days,
        example_limit=thresholds.example_limit,
    )
    gcs_trends = summarize_jobs_for_gcs(classified_jobs)

    run_id = str(uuid4())
    summary_path = _summary_path_for(output_path)
    jobs_path = output_path if jobs_only else _jobs_path_for(output_path)
    data_quality_path = _data_quality_path_for(output_path)
    gcs_trends_path = _gcs_trends_path_for(output_path)

    artifacts = {
        "matches": None if jobs_only else str(output_path),
        "jobs": str(jobs_path),
        "data_quality": str(data_quality_path),
        "gcs_trends": str(gcs_trends_path),
        "summary": str(summary_path),
    }

    if dry_run:
        warnings.append("Dry run requested; output files were not written.")
        LOGGER.info("Dry run requested; skipping output writes")

    summary = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": "jobs-only" if jobs_only else "student-matching",
        "source": source_name,
        "source_since_date": source_since_date,
        "source_limit": source_limit,
        "full_refresh": full_refresh,
        "company_careers_health": source_load.company_health,
        "apify_linkedin_health": source_load.apify_health,
        "input_path": None if input_path is None else str(input_path),
        "profiles_path": None if profiles_path is None else str(profiles_path),
        "output_path": str(output_path),
        "artifacts": artifacts,
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
        "data_quality_summary": {
            "overall_completeness_pct": data_quality_report["overall_completeness_pct"],
            "issue_counts": {
                issue["key"]: issue["count"]
                for issue in data_quality_report["issues"]
                if issue["count"]
            },
        },
        "warnings": warnings,
        "errors": [],
        "runtime_seconds": round(perf_counter() - started_at, 3),
    }

    if not dry_run:
        store: JobStore | None = None
        make_store = store_factory or (
            lambda url: create_job_store(url, storage=storage)
        )
        try:
            if not skip_store:
                resolved_database_url = (
                    database_url
                    if database_url is not None
                    else settings.database_url.get_secret_value()
                )
                store = make_store(resolved_database_url)
                store.preflight()

            if jobs_only:
                _write_jobs(output_path, classified_jobs)
            else:
                _write_results(output_path, ranked_rows)
                _write_jobs(jobs_path, classified_jobs)
            _write_json(data_quality_path, data_quality_report)
            _write_json(gcs_trends_path, gcs_trends)

            if store is not None:
                store.persist_pipeline_run(
                    run_id=run_id,
                    run_type="mvp",
                    source=source_name,
                    summary=summary,
                    normalized_jobs=normalized_jobs,
                    valid_jobs=valid_jobs,
                    deduped_jobs=classified_jobs,
                    ranked_matches=[
                        (ranked.profile, ranked.matches)
                        for ranked in ranked_profile_matches
                    ],
                    input_path=input_path,
                    profiles_path=profiles_path,
                    output_path=output_path,
                )
        except JobStoreError as exc:
            raise MvpPipelineError(str(exc)) from exc
        finally:
            if store is not None:
                store.close()
        _write_summary(summary_path, summary)

    return MvpPipelineResult(
        output_path=output_path,
        summary_path=summary_path,
        rows=ranked_rows,
        summary=summary,
    )


def _load_source(
    source_name: str,
    input_path: Path | None,
    source_since_date: str | None = None,
    source_limit: int | None = None,
    company_config_path: Path | None = None,
    local_source: str = "kelleylink_excel",
    company_source: CompanyCareersSource | None = None,
    apify_dataset_id: str | None = None,
    apify_run_id: str | None = None,
    apify_trigger_run: bool = False,
    apify_max_items: int | None = None,
) -> SourceLoadResult:
    """Load jobs from one or more approved sources.

    Supported ``source_name`` values:

    * ``company_careers``: fetch public ATS boards from the company config.
    * ``apify_linkedin``: fetch LinkedIn postings collected by the approved
      Apify actor on the user's account.
    * ``all``: company_careers plus apify_linkedin (when APIFY_TOKEN is set)
      plus, when ``input_path`` is provided, a local export loaded with
      ``local_source`` (defaults to ``kelleylink_excel``).
    * ``approved_json`` / ``ksbit_export`` / ``kelleylink_excel``: local export
      requiring ``input_path``.
    """

    if source_name == "company_careers":
        return _load_company_careers(
            config_path=company_config_path or input_path,
            company_source=company_source,
        )

    if source_name == "apify_linkedin":
        return _load_apify_linkedin(
            dataset_id=apify_dataset_id,
            run_id=apify_run_id,
            trigger_run=apify_trigger_run,
            max_items=apify_max_items,
        )

    if source_name == "all":
        return _load_all_sources(
            input_path=input_path,
            source_since_date=source_since_date,
            source_limit=source_limit,
            company_config_path=company_config_path,
            local_source=local_source,
            company_source=company_source,
            apify_dataset_id=apify_dataset_id,
            apify_run_id=apify_run_id,
            apify_trigger_run=apify_trigger_run,
            apify_max_items=apify_max_items,
        )

    return _load_local_source(
        source_name=source_name,
        input_path=input_path,
        source_since_date=source_since_date,
        source_limit=source_limit,
    )


def _load_apify_linkedin(
    *,
    dataset_id: str | None,
    run_id: str | None,
    trigger_run: bool,
    max_items: int | None,
    settings: ApifyLinkedInSettings | None = None,
) -> SourceLoadResult:
    """Fetch and pre-filter LinkedIn postings from the approved Apify actor."""

    try:
        ensure_source_allowed("apify_linkedin")
    except SourceComplianceError as exc:
        raise MvpPipelineError(str(exc)) from exc

    LOGGER.info("Loading source adapter: apify_linkedin")
    source = ApifyLinkedInSource(
        settings=settings,
        dataset_id=dataset_id,
        run_id=run_id,
        trigger_run=trigger_run,
        max_items=max_items,
    )
    try:
        result = source.fetch_jobs_with_warnings()
    except ApifyLinkedInSourceError as exc:
        raise MvpPipelineError(str(exc)) from exc

    return SourceLoadResult(
        source=source,
        jobs=result.jobs,
        raw_count=result.raw_count,
        warnings=result.warnings,
        apify_health=result.to_summary(),
    )


def _load_company_careers(
    config_path: Path | None,
    company_source: CompanyCareersSource | None = None,
) -> SourceLoadResult:
    """Fetch and pre-filter public ATS company career postings."""

    LOGGER.info("Loading source adapter: company_careers")
    try:
        source = company_source or CompanyCareersSource(config_path=config_path)
        result = source.fetch_all_jobs()
    except CompanyCareersConfigError as exc:
        raise MvpPipelineError(str(exc)) from exc

    return SourceLoadResult(
        source=source,
        jobs=result.jobs,
        raw_count=result.raw_count,
        warnings=result.warnings,
        company_health=result.to_summary(),
    )


def _load_all_sources(
    *,
    input_path: Path | None,
    source_since_date: str | None,
    source_limit: int | None,
    company_config_path: Path | None,
    local_source: str,
    company_source: CompanyCareersSource | None,
    apify_dataset_id: str | None = None,
    apify_run_id: str | None = None,
    apify_trigger_run: bool = False,
    apify_max_items: int | None = None,
) -> SourceLoadResult:
    """Combine company_careers, apify_linkedin, and an optional local export."""

    company = _load_company_careers(
        config_path=company_config_path,
        company_source=company_source,
    )
    jobs = list(company.jobs)
    raw_count = company.raw_count
    warnings = list(company.warnings)

    apify: SourceLoadResult | None = None
    apify_settings = ApifyLinkedInSettings()
    if apify_settings.apify_token.get_secret_value().strip():
        try:
            apify = _load_apify_linkedin(
                dataset_id=apify_dataset_id,
                run_id=apify_run_id,
                trigger_run=apify_trigger_run,
                max_items=apify_max_items,
                settings=apify_settings,
            )
        except MvpPipelineError as exc:
            warnings.append(f"Source 'all' skipped apify_linkedin: {exc}")
    else:
        warnings.append(
            "Source 'all' skipped apify_linkedin because APIFY_TOKEN is not set."
        )
    if apify is not None:
        jobs.extend(apify.jobs)
        raw_count += apify.raw_count
        warnings.extend(apify.warnings)

    if input_path is not None:
        local = _load_local_source(
            source_name=local_source,
            input_path=input_path,
            source_since_date=source_since_date,
            source_limit=source_limit,
        )
        jobs.extend(local.jobs)
        raw_count += local.raw_count
        warnings.extend(local.warnings)

    return SourceLoadResult(
        source=company.source,
        jobs=jobs,
        raw_count=raw_count,
        warnings=warnings,
        company_health=company.company_health,
        apify_health=apify.apify_health if apify is not None else None,
    )


def _load_local_source(
    source_name: str,
    input_path: Path | None,
    source_since_date: str | None = None,
    source_limit: int | None = None,
) -> SourceLoadResult:
    """Load jobs from an approved local file-based source adapter."""

    if input_path is None:
        raise MvpPipelineError(f"--input is required for source '{source_name}'")
    _require_file(input_path, "Input file")
    try:
        source = create_source_adapter(
            source_name,
            input_path,
            source_since_date=source_since_date,
            source_limit=source_limit,
        )
    except SourceComplianceError as exc:
        raise MvpPipelineError(str(exc)) from exc

    LOGGER.info("Loading source adapter: %s", source_name)
    if source_name == "approved_json":
        if not isinstance(source, ApprovedJsonJobSource):
            raise MvpPipelineError(
                "Source registry returned the wrong adapter for approved_json"
            )
        try:
            approved_result = source.fetch_jobs_with_warnings()
        except ApprovedJsonSourceError as exc:
            raise MvpPipelineError(str(exc)) from exc
        return SourceLoadResult(
            source=source,
            jobs=approved_result.jobs,
            raw_count=approved_result.raw_count,
            warnings=approved_result.warnings,
        )

    if source_name in {"ksbit_export", "kelleylink_excel"}:
        if not isinstance(source, KsbitExportSource):
            raise MvpPipelineError(
                f"Source registry returned the wrong adapter for {source_name}"
            )
        try:
            ksbit_result = source.fetch_jobs_with_warnings()
        except KsbitExportSourceError as exc:
            raise MvpPipelineError(str(exc)) from exc
        return SourceLoadResult(
            source=source,
            jobs=ksbit_result.jobs,
            raw_count=ksbit_result.raw_count,
            warnings=ksbit_result.warnings,
        )

    raise MvpPipelineError(
        "MVP runner supports --source approved_json, ksbit_export, "
        "kelleylink_excel, company_careers, or all"
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
                f"Classifier failed for job {index}; exporting unclassified job: {exc}"
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
) -> list[RankedProfileMatches]:
    """Rank jobs for every consenting profile."""

    ranked_profiles: list[RankedProfileMatches] = []
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
        ranked_profiles.append(RankedProfileMatches(profile=profile, matches=matches))

    return ranked_profiles


def _match_to_row(profile: StudentProfile, match: JobMatch) -> dict[str, Any]:
    """Convert one ranked match into the documented MVP export fields."""

    job = match.job
    reasons = match.reasons
    score_breakdown = match.metadata.get("score_breakdown", {})
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


def _write_jobs(output_path: Path, jobs: Sequence[JobPosting]) -> None:
    """Write normalized + classified postings to CSV (default) or JSON."""

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.casefold() == ".json":
            payload = [job.model_dump(mode="json") for job in jobs]
            output_path.write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
            return

        with output_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=JOBS_OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(_job_to_row(job) for job in jobs)
    except OSError as exc:
        raise MvpPipelineError(
            f"Jobs output path could not be written: {output_path}: {exc}"
        ) from exc


def _write_json(output_path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON artifact (data-quality report or GCS trend summary)."""

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        raise MvpPipelineError(
            f"Artifact path could not be written: {output_path}: {exc}"
        ) from exc


def _job_to_row(job: JobPosting) -> dict[str, Any]:
    """Convert a normalized posting into the documented jobs export fields."""

    return {
        "source": job.source,
        "source_job_id": job.source_job_id or "",
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "apply_url/post_url": job.url,
        "posted_date": job.posted_date.isoformat() if job.posted_date else "",
        "employment_type": job.employment_type or "",
        "seniority": job.seniority or "",
        "role_tags": "; ".join(job.role_tags),
        "concentration_tags": "; ".join(job.concentration_tags),
        "opt_cpt_flag": job.opt_cpt_flag,
        "classification_uncertain": job.classification_uncertain,
        "retrieved_at": job.retrieved_at.isoformat() if job.retrieved_at else "",
    }


def _write_summary(summary_path: Path, summary: dict[str, Any]) -> None:
    """Write the run summary JSON beside the results file."""

    try:
        summary_path.write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        raise MvpPipelineError(
            f"Summary path could not be written: {summary_path}: {exc}"
        ) from exc


def _summary_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.summary.json")


def _jobs_path_for(output_path: Path) -> Path:
    suffix = output_path.suffix or ".csv"
    return output_path.with_name(f"{output_path.stem}.jobs{suffix}")


def _data_quality_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.data_quality.json")


def _gcs_trends_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.gcs_trends.json")


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
    parser.add_argument(
        "--source",
        required=True,
        help=(
            "Approved source: approved_json, ksbit_export, kelleylink_excel, "
            "company_careers, apify_linkedin, or all."
        ),
    )
    parser.add_argument(
        "--input",
        required=False,
        default=None,
        type=Path,
        help=(
            "Path to a local job export. Required for approved_json/ksbit_export/"
            "kelleylink_excel. Optional for company_careers and all."
        ),
    )
    parser.add_argument(
        "--company-config",
        type=Path,
        default=None,
        help=(
            "Path to the company_careers YAML/JSON config. Defaults to "
            f"{DEFAULT_COMPANY_CONFIG_PATH}."
        ),
    )
    parser.add_argument(
        "--local-source",
        default="kelleylink_excel",
        help=(
            "For --source all, the local export adapter to combine with "
            "company_careers. Defaults to kelleylink_excel."
        ),
    )
    parser.add_argument(
        "--apify-run-id",
        default=None,
        help=(
            "For apify_linkedin/all, read the dataset of this specific Apify "
            "actor run instead of the latest successful run."
        ),
    )
    parser.add_argument(
        "--apify-dataset-id",
        default=None,
        help="For apify_linkedin/all, read this Apify dataset id directly.",
    )
    parser.add_argument(
        "--apify-trigger-run",
        action="store_true",
        help=(
            "For apify_linkedin/all, start a NEW paid Apify actor run with "
            "MSIS-tuned keywords and wait for it to finish. Charges the "
            "configured Apify account; off by default."
        ),
    )
    parser.add_argument(
        "--apify-max-items",
        type=int,
        default=None,
        help="For apify_linkedin/all, maximum dataset items to download.",
    )
    parser.add_argument(
        "--profiles",
        type=Path,
        default=None,
        help=(
            "Path to student profiles JSON. Omit to run jobs-only mode "
            "(normalized jobs, data-quality report, and GCS trends)."
        ),
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
        "--skip-store",
        action="store_true",
        help="Write output artifacts but skip SQLite persistence.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help=(
            "Treat this run as a complete re-crawl of the source: postings that "
            "are absent from the run are marked inactive. Only safe when every "
            "company in the source succeeded."
        ),
    )
    parser.add_argument(
        "--dq-short-description-chars",
        type=int,
        default=None,
        help=(
            "Data-quality: descriptions shorter than this are flagged. "
            "Overrides data/data_quality_thresholds.json."
        ),
    )
    parser.add_argument(
        "--dq-stale-days",
        type=int,
        default=None,
        help=(
            "Data-quality: postings older than this many days are flagged. "
            "Overrides data/data_quality_thresholds.json."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Persistence target URL. Defaults to DATABASE_URL, or "
            "data/hope_job_agent.sqlite3 when unset."
        ),
    )
    parser.add_argument(
        "--storage",
        choices=("auto", "sqlite", "postgres", "memory"),
        default="auto",
        help=(
            "Persistence backend: auto (from DATABASE_URL), sqlite, postgres, "
            "or memory."
        ),
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

    thresholds = load_data_quality_thresholds()
    if args.dq_short_description_chars is not None or args.dq_stale_days is not None:
        thresholds = DataQualityThresholds(
            short_description_chars=(
                args.dq_short_description_chars
                if args.dq_short_description_chars is not None
                else thresholds.short_description_chars
            ),
            stale_after_days=(
                args.dq_stale_days
                if args.dq_stale_days is not None
                else thresholds.stale_after_days
            ),
            example_limit=thresholds.example_limit,
        )

    try:
        result = run_mvp_pipeline(
            source_name=args.source,
            input_path=args.input,
            profiles_path=args.profiles,
            output_path=args.output,
            limit=args.limit,
            source_since_date=args.source_since_date,
            source_limit=args.source_limit,
            company_config_path=args.company_config,
            local_source=args.local_source,
            apify_dataset_id=args.apify_dataset_id,
            apify_run_id=args.apify_run_id,
            apify_trigger_run=args.apify_trigger_run,
            apify_max_items=args.apify_max_items,
            dry_run=args.dry_run,
            skip_store=args.skip_store,
            full_refresh=args.full_refresh,
            verbose=args.verbose,
            database_url=args.database_url,
            storage=args.storage,
            data_quality_thresholds=thresholds,
        )
    except MvpPipelineError as exc:
        print(f"MVP pipeline failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    summary = result.summary
    print("MVP pipeline run complete")
    print(f"Run ID: {summary['run_id']}")
    print(f"Mode: {summary['mode']}")
    print(f"Source: {summary['source']}")
    print(f"Raw jobs: {summary['raw_count']}")
    print(f"Unique jobs: {summary['unique_count']}")
    health = summary.get("company_careers_health")
    if health:
        print(
            "Company careers: "
            f"fetched={health['raw_count']} kept={health['kept_count']} "
            f"duplicates={health['duplicate_count']} "
            f"ok={health['companies_ok']}/{health['companies_total']}"
        )
        for company in health.get("per_company", []):
            print(
                f"  - {company['company_name']} [{company['provider']}]: "
                f"status={company['status']} fetched={company['fetched']} "
                f"kept={company['kept']} skipped_kw={company['skipped_by_keyword']} "
                f"skipped_filter={company['skipped_by_filter']}"
                + (f" error={company['error']}" if company.get("error") else "")
            )
        if health.get("failed_companies"):
            print(f"  Failed companies: {', '.join(health['failed_companies'])}")
    apify_health = summary.get("apify_linkedin_health")
    if apify_health:
        print(
            "Apify LinkedIn: "
            f"run={apify_health['run_id']} dataset={apify_health['dataset_id']} "
            f"fetched={apify_health['raw_count']} kept={apify_health['kept_count']} "
            f"skipped_relevance={apify_health['skipped_by_relevance']}"
        )
    print(f"Profiles: {summary['profile_count']}")
    print(f"Ranked matches: {summary['total_ranked_matches']}")
    print(
        "Data completeness: "
        f"{summary['data_quality_summary']['overall_completeness_pct']}%"
    )
    print(f"Output file: {result.output_path}")
    if args.dry_run:
        print("Artifacts: not written (--dry-run)")
    else:
        print(f"Jobs file: {summary['artifacts']['jobs']}")
        print(f"Data quality file: {summary['artifacts']['data_quality']}")
        print(f"GCS trends file: {summary['artifacts']['gcs_trends']}")
        print(f"Summary file: {result.summary_path}")
    if summary["warnings"]:
        print(f"Warnings: {len(summary['warnings'])}")


if __name__ == "__main__":
    main()

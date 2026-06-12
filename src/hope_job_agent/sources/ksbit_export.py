"""KSBIT-compatible local export adapter.

This adapter intentionally reads local JSON/CSV exports only. It performs no
scraping, browser automation, login automation, or credentialed access.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.utils.hashing import stable_hash

KSBIT_SOURCE_NAME = "ksbit_export"
DEFAULT_LOCATION = "Not specified"

JSON_WRAPPER_KEYS = ("jobs", "data", "results", "postings", "job_postings")

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_job_id": (
        "source_job_id",
        "job_id",
        "id",
        "posting_id",
        "requisition_id",
        "req_id",
    ),
    "title": ("title", "job_title", "position_title", "role", "name"),
    "company": (
        "company",
        "employer",
        "employer_name",
        "organization",
        "company_name",
    ),
    "location": (
        "location",
        "job_location",
        "city",
        "work_location",
        "office_location",
    ),
    "description": (
        "description",
        "job_description",
        "full_description",
        "summary",
    ),
    "apply_url": (
        "apply_url",
        "post_url",
        "job_url",
        "url",
        "application_url",
        "apply_link",
    ),
    "posted_date": ("posted_date", "date_posted", "created_at", "published_at"),
    "employment_type": (
        "employment_type",
        "job_type",
        "position_type",
        "work_type",
    ),
    "seniority_level": (
        "seniority_level",
        "seniority",
        "experience_level",
        "level",
    ),
}

OPTIONAL_DIRECT_FIELDS = (
    "concentration_tags",
    "role_tags",
    "opt_cpt_flag",
)


class KsbitExportSourceError(ValueError):
    """Raised when a KSBIT local export cannot be loaded safely."""


@dataclass(frozen=True)
class KsbitExportFetchResult:
    """Jobs loaded from a KSBIT export plus adapter-level counts."""

    jobs: list[JobPosting]
    raw_count: int
    loaded_count: int
    skipped_count: int
    returned_count: int
    warnings: list[str]


class KsbitExportSource(BaseJobSource):
    """Read KSBIT-compatible local JSON/CSV exports."""

    source_name = KSBIT_SOURCE_NAME

    def __init__(
        self,
        export_path: str | Path,
        *,
        since_date: str | date | None = None,
        limit: int | None = None,
    ) -> None:
        """Create a local KSBIT export adapter."""

        self.export_path = Path(export_path)
        self.since_date = _coerce_since_date(since_date)
        self.limit = limit
        if self.limit is not None and self.limit < 1:
            raise KsbitExportSourceError("limit must be a positive integer")

    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch jobs from a local KSBIT export."""

        return self.fetch_jobs_with_warnings().jobs

    def fetch_jobs_with_warnings(self) -> KsbitExportFetchResult:
        """Fetch jobs while skipping invalid individual export rows."""

        raw_records = self._load_records()
        warnings: list[str] = []
        ingested_at = datetime.now(UTC)
        jobs: list[JobPosting] = []

        for index, raw_record in enumerate(raw_records, start=1):
            job = _record_to_job(raw_record, index, ingested_at, warnings)
            if job is not None:
                jobs.append(job)

        if not jobs:
            raise KsbitExportSourceError(
                f"No valid KSBIT job records found in export: {self.export_path}"
            )

        filtered_jobs = _filter_since_date(jobs, self.since_date, warnings)
        if self.limit is not None:
            filtered_jobs = filtered_jobs[: self.limit]

        return KsbitExportFetchResult(
            jobs=filtered_jobs,
            raw_count=len(raw_records),
            loaded_count=len(jobs),
            skipped_count=len(raw_records) - len(jobs),
            returned_count=len(filtered_jobs),
            warnings=warnings,
        )

    def health_check(self) -> bool:
        """Return whether the local export can be loaded and has valid jobs."""

        try:
            self.fetch_jobs_with_warnings()
        except KsbitExportSourceError:
            return False
        return True

    def _load_records(self) -> list[dict[str, Any]]:
        """Load raw export records from JSON or CSV."""

        _require_readable_file(self.export_path)
        suffix = self.export_path.suffix.casefold()
        if suffix == ".json":
            records = self._load_json_records()
        elif suffix == ".csv":
            records = self._load_csv_records()
        else:
            raise KsbitExportSourceError(
                "Unsupported KSBIT export extension "
                f"'{self.export_path.suffix}'. Use .json or .csv."
            )

        if not records:
            raise KsbitExportSourceError(f"KSBIT export is empty: {self.export_path}")
        return records

    def _load_json_records(self) -> list[dict[str, Any]]:
        """Load records from a JSON list or a known wrapper key."""

        try:
            raw_text = self.export_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise KsbitExportSourceError(
                f"KSBIT export could not be read: {self.export_path}: {exc}"
            ) from exc

        if not raw_text.strip():
            raise KsbitExportSourceError(f"KSBIT export is empty: {self.export_path}")

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise KsbitExportSourceError(
                f"KSBIT JSON export is not valid JSON: {self.export_path}: {exc.msg}"
            ) from exc

        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = _records_from_wrapper(payload, self.export_path)
        else:
            raise KsbitExportSourceError(
                "KSBIT JSON export must be a list or an object containing one "
                f"of these arrays: {', '.join(JSON_WRAPPER_KEYS)}"
            )

        return _ensure_record_dicts(records, self.export_path)

    def _load_csv_records(self) -> list[dict[str, Any]]:
        """Load records from CSV headers and rows."""

        try:
            with self.export_path.open(newline="", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                return [dict(row) for row in reader]
        except csv.Error as exc:
            raise KsbitExportSourceError(
                f"KSBIT CSV export could not be parsed: {self.export_path}: {exc}"
            ) from exc
        except OSError as exc:
            raise KsbitExportSourceError(
                f"KSBIT export could not be read: {self.export_path}: {exc}"
            ) from exc


def _record_to_job(
    raw_record: Mapping[str, Any],
    row_number: int,
    ingested_at: datetime,
    warnings: list[str],
) -> JobPosting | None:
    mapped = _map_aliases(raw_record)
    missing_fields = [
        field
        for field in ("title", "company", "description", "apply_url")
        if not _text_value(mapped.get(field))
    ]
    if missing_fields:
        warnings.append(
            "Skipped KSBIT row "
            f"{row_number}: missing required field(s): {', '.join(missing_fields)}"
        )
        return None

    posted_date = _parse_posted_date(mapped.get("posted_date"))
    location = _text_value(mapped.get("location")) or DEFAULT_LOCATION
    source_job_id = _text_value(mapped.get("source_job_id"))
    generated_source_job_id = source_job_id is None
    if source_job_id is None:
        source_job_id = _fallback_source_job_id(
            company=str(mapped["company"]),
            title=str(mapped["title"]),
            location=location,
            apply_url=str(mapped["apply_url"]),
        )

    raw_payload = dict(raw_record)
    raw_metadata = {
        "raw_payload": raw_payload,
        "ingested_at": ingested_at.isoformat(),
        "source_job_id_was_generated": generated_source_job_id,
    }

    try:
        return JobPosting(
            source=KSBIT_SOURCE_NAME,
            source_job_id=source_job_id,
            title=str(mapped["title"]),
            company=str(mapped["company"]),
            location=location,
            description=str(mapped["description"]),
            url=str(mapped["apply_url"]),
            posted_date=posted_date,
            employment_type=_text_value(mapped.get("employment_type")),
            seniority=_text_value(mapped.get("seniority_level")),
            concentration_tags=_list_value(mapped.get("concentration_tags")),
            role_tags=_list_value(mapped.get("role_tags")),
            opt_cpt_flag=_bool_value(mapped.get("opt_cpt_flag")),
            raw_metadata=raw_metadata,
            retrieved_at=ingested_at,
        )
    except ValidationError as exc:
        warnings.append(
            "Skipped KSBIT row "
            f"{row_number}: failed job validation: {_summarize_validation_error(exc)}"
        )
        return None


def _map_aliases(raw_record: Mapping[str, Any]) -> dict[str, Any]:
    normalized_record = {
        _normalize_key(str(key)): value for key, value in raw_record.items() if key
    }
    mapped: dict[str, Any] = {}
    for field, aliases in FIELD_ALIASES.items():
        mapped[field] = _first_present_value(normalized_record, aliases)

    for field in OPTIONAL_DIRECT_FIELDS:
        mapped[field] = _first_present_value(normalized_record, (field,))

    return mapped


def _records_from_wrapper(payload: dict[str, Any], export_path: Path) -> Any:
    for key in JSON_WRAPPER_KEYS:
        if key in payload:
            records = payload[key]
            if not isinstance(records, list):
                raise KsbitExportSourceError(
                    f"KSBIT JSON wrapper key '{key}' must contain a list: {export_path}"
                )
            return records
    raise KsbitExportSourceError(
        "KSBIT JSON export must contain one of these array keys: "
        f"{', '.join(JSON_WRAPPER_KEYS)}"
    )


def _ensure_record_dicts(records: list[Any], export_path: Path) -> list[dict[str, Any]]:
    if not all(isinstance(record, dict) for record in records):
        raise KsbitExportSourceError(
            f"KSBIT export records must be JSON objects: {export_path}"
        )
    return [dict(record) for record in records]


def _filter_since_date(
    jobs: list[JobPosting],
    since_date: date | None,
    warnings: list[str],
) -> list[JobPosting]:
    if since_date is None:
        return jobs

    filtered_jobs: list[JobPosting] = []
    for job in jobs:
        if job.posted_date is None:
            warnings.append(
                "Included KSBIT row without parseable posted_date during "
                f"since_date filtering: {job.source_job_id}"
            )
            filtered_jobs.append(job)
            continue
        if job.posted_date >= since_date:
            filtered_jobs.append(job)
    return filtered_jobs


def _fallback_source_job_id(
    *,
    company: str,
    title: str,
    location: str,
    apply_url: str,
) -> str:
    return "ksbit-" + stable_hash(f"{company}|{title}|{location}|{apply_url}")[:16]


def _parse_posted_date(value: Any) -> date | None:
    text = _text_value(value)
    if text is None:
        return None

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _coerce_since_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise KsbitExportSourceError(
            f"since_date must use YYYY-MM-DD format: {value}"
        ) from exc


def _first_present_value(
    normalized_record: Mapping[str, Any],
    aliases: tuple[str, ...],
) -> Any:
    for alias in aliases:
        value = normalized_record.get(_normalize_key(alias))
        if _text_value(value) is not None or isinstance(value, (list, bool)):
            return value
    return None


def _normalize_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    separator = ";" if ";" in text else ","
    return [item.strip() for item in text.split(separator) if item.strip()]


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text_value(value)
    if text is None:
        return None
    normalized = text.casefold()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    return None


def _require_readable_file(path: Path) -> None:
    if not path.exists():
        raise KsbitExportSourceError(f"KSBIT export not found: {path}")
    if not path.is_file():
        raise KsbitExportSourceError(f"KSBIT export path is not a file: {path}")


def _summarize_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    first_error = errors[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    message = first_error.get("msg", str(exc))
    return f"{location}: {message}" if location else str(message)

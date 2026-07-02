"""KSBIT-compatible local export adapter.

This adapter intentionally reads local JSON/CSV/XLSX exports only. It performs
no scraping, browser automation, login automation, or credentialed access.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import unescape
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.utils.hashing import stable_hash

LOGGER = logging.getLogger(__name__)

KSBIT_SOURCE_NAME = "ksbit_export"
DEFAULT_LOCATION = "Not specified"
DEFAULT_ALLOWED_STATUSES = frozenset({"Application Open"})
INTERNAL_ROW_NUMBER_FIELD = "__ksbit_source_row_number"
INTERNAL_SOURCE_FORMAT_FIELD = "__ksbit_source_format"

SENSITIVE_ANALYTICS_FIELDS = {
    "application_count",
    "distinct_applicant_count",
    "first_application_date",
    "last_application_date",
}

JSON_WRAPPER_KEYS = ("jobs", "data", "results", "postings", "job_postings")

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_job_id": (
        "source_job_id",
        "job_posting_id",
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
    "status": ("status",),
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
    "location_type",
    "work_authorization_requirement",
    "other_work_authorization",
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
    """Read KSBIT-compatible local JSON/CSV/XLSX exports."""

    source_name = KSBIT_SOURCE_NAME

    def __init__(
        self,
        export_path: str | Path,
        *,
        since_date: str | date | None = None,
        limit: int | None = None,
        allowed_statuses: set[str] | frozenset[str] | None = DEFAULT_ALLOWED_STATUSES,
    ) -> None:
        """Create a local KSBIT export adapter."""

        self.export_path = Path(export_path)
        self.since_date = _coerce_since_date(since_date)
        self.limit = limit
        self.allowed_statuses = (
            None
            if allowed_statuses is None
            else frozenset(
                status.strip() for status in allowed_statuses if status.strip()
            )
        )
        if self.limit is not None and self.limit < 1:
            raise KsbitExportSourceError("limit must be a positive integer")

    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch jobs from a local KSBIT export."""

        return self.fetch_jobs_with_warnings().jobs

    def fetch_jobs_with_warnings(self) -> KsbitExportFetchResult:
        """Fetch jobs while skipping invalid individual export rows."""

        warnings: list[str] = []
        LOGGER.info("Loading KSBIT export from %s", self.export_path)
        raw_records = self._load_records()
        source_records = _filter_allowed_statuses(
            raw_records=raw_records,
            allowed_statuses=self.allowed_statuses,
            warnings=warnings,
        )
        ingested_at = datetime.now(UTC)
        jobs: list[JobPosting] = []

        for index, raw_record in enumerate(source_records, start=1):
            row_number = _record_row_number(raw_record, fallback=index)
            job = _record_to_job(raw_record, row_number, ingested_at, warnings)
            if job is not None:
                jobs.append(job)

        if not jobs:
            raise KsbitExportSourceError(
                f"No valid KSBIT job records found in export: {self.export_path}"
            )

        filtered_jobs = _filter_since_date(jobs, self.since_date, warnings)
        if self.limit is not None:
            filtered_jobs = filtered_jobs[: self.limit]
        compact_warnings = _compact_repeated_warnings(warnings)
        for warning in compact_warnings:
            LOGGER.warning(warning)
        LOGGER.info(
            "Loaded KSBIT export: raw=%s loaded=%s skipped=%s returned=%s",
            len(raw_records),
            len(jobs),
            len(raw_records) - len(jobs),
            len(filtered_jobs),
        )

        return KsbitExportFetchResult(
            jobs=filtered_jobs,
            raw_count=len(raw_records),
            loaded_count=len(jobs),
            skipped_count=len(raw_records) - len(jobs),
            returned_count=len(filtered_jobs),
            warnings=compact_warnings,
        )

    def health_check(self) -> bool:
        """Return whether the local export can be loaded and has valid jobs."""

        try:
            self.fetch_jobs_with_warnings()
        except KsbitExportSourceError:
            return False
        return True

    def _load_records(self) -> list[dict[str, Any]]:
        """Load raw export records from JSON, CSV, or XLSX."""

        _require_readable_file(self.export_path)
        suffix = self.export_path.suffix.casefold()
        if suffix == ".json":
            records = self._load_json_records()
        elif suffix == ".csv":
            records = self._load_csv_records()
        elif suffix == ".xlsx":
            records = self._load_xlsx_records()
        else:
            raise KsbitExportSourceError(
                "Unsupported KSBIT export extension "
                f"'{self.export_path.suffix}'. Use .json, .csv, or .xlsx."
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

    def _load_xlsx_records(self) -> list[dict[str, Any]]:
        """Load records from the first worksheet in a 12Twenty Excel export."""

        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise KsbitExportSourceError(
                "Reading .xlsx KSBIT exports requires openpyxl>=3.1. "
                "Install project runtime dependencies before loading Excel exports."
            ) from exc

        try:
            workbook = load_workbook(
                self.export_path,
                read_only=True,
                data_only=True,
            )
        except OSError as exc:
            raise KsbitExportSourceError(
                f"KSBIT Excel export could not be read: {self.export_path}: {exc}"
            ) from exc
        except Exception as exc:
            raise KsbitExportSourceError(
                f"KSBIT Excel export could not be parsed: {self.export_path}: {exc}"
            ) from exc

        try:
            worksheet = workbook.worksheets[0]
            header_row_number, headers = _find_xlsx_headers(worksheet)
            _validate_xlsx_headers(headers, self.export_path)

            records: list[dict[str, Any]] = []
            for row_number, row in enumerate(
                worksheet.iter_rows(
                    min_row=header_row_number + 1,
                    values_only=True,
                ),
                start=header_row_number + 1,
            ):
                if _row_is_empty(row):
                    continue
                record = {
                    header: _safe_metadata_value(value)
                    for header, value in zip(headers, row, strict=False)
                }
                record[INTERNAL_ROW_NUMBER_FIELD] = row_number
                record[INTERNAL_SOURCE_FORMAT_FIELD] = "xlsx"
                records.append(record)
            return records
        finally:
            workbook.close()

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
    description = _clean_description(mapped.get("description"))
    missing_fields = [
        field
        for field in ("title", "company", "description", "apply_url")
        if not _text_value(description if field == "description" else mapped.get(field))
    ]
    if missing_fields:
        warnings.append(
            "Skipped KSBIT row "
            f"{row_number}: missing required field(s): {', '.join(missing_fields)}"
        )
        return None

    posted_date = _parse_posted_date(mapped.get("posted_date"))
    location = _format_location(
        mapped.get("location"),
        location_type=mapped.get("location_type"),
    )
    source_job_id = _text_value(mapped.get("source_job_id"))
    generated_source_job_id = source_job_id is None
    if source_job_id is None:
        source_job_id = _fallback_source_job_id(
            company=str(_text_value(mapped["company"])),
            title=str(_text_value(mapped["title"])),
            location=location,
            apply_url=str(_text_value(mapped["apply_url"])),
        )

    raw_payload = _raw_payload_for_metadata(raw_record)
    raw_metadata = {
        "raw_payload": raw_payload,
        "ingested_at": ingested_at.isoformat(),
        "source_job_id_was_generated": generated_source_job_id,
    }
    if INTERNAL_ROW_NUMBER_FIELD in raw_record:
        raw_metadata["source_row_number"] = _record_row_number(raw_record, row_number)
    if INTERNAL_SOURCE_FORMAT_FIELD in raw_record:
        raw_metadata["source_format"] = _text_value(
            raw_record.get(INTERNAL_SOURCE_FORMAT_FIELD)
        )

    try:
        return JobPosting(
            source=KSBIT_SOURCE_NAME,
            source_job_id=source_job_id,
            title=str(_text_value(mapped["title"])),
            company=str(_text_value(mapped["company"])),
            location=location,
            description=str(description),
            url=str(_text_value(mapped["apply_url"])),
            posted_date=posted_date,
            employment_type=_text_value(mapped.get("employment_type")),
            seniority=_text_value(mapped.get("seniority_level")),
            concentration_tags=_list_value(mapped.get("concentration_tags")),
            role_tags=_list_value(mapped.get("role_tags")),
            opt_cpt_flag=_resolve_opt_cpt_flag(mapped),
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


def _filter_allowed_statuses(
    *,
    raw_records: list[dict[str, Any]],
    allowed_statuses: frozenset[str] | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Filter source rows by 12Twenty status, if the export includes one."""

    if allowed_statuses is None:
        return raw_records

    allowed_normalized = {
        normalized
        for status in allowed_statuses
        if (normalized := _normalize_status(status))
    }
    if not allowed_normalized:
        return raw_records

    filtered_records: list[dict[str, Any]] = []
    skipped_by_status: dict[str, int] = {}
    for raw_record in raw_records:
        status = _text_value(_map_aliases(raw_record).get("status"))
        if status is None:
            filtered_records.append(raw_record)
            continue
        if _normalize_status(status) in allowed_normalized:
            filtered_records.append(raw_record)
            continue
        skipped_by_status[status] = skipped_by_status.get(status, 0) + 1

    if skipped_by_status:
        status_counts = ", ".join(
            f"{status}={count}" for status, count in sorted(skipped_by_status.items())
        )
        warnings.append(
            "Skipped KSBIT rows with disallowed status: "
            f"{status_counts}. Allowed statuses: {', '.join(sorted(allowed_statuses))}"
        )
    return filtered_records


def _normalize_status(value: str) -> str:
    return " ".join(value.casefold().split())


def _compact_repeated_warnings(warnings: list[str]) -> list[str]:
    grouped_row_warnings: dict[str, list[str]] = {}
    compact_warnings: list[str] = []

    for warning in warnings:
        match = re.fullmatch(r"Skipped KSBIT row (\d+): (.+)", warning)
        if match is None:
            compact_warnings.append(warning)
            continue
        row_number, reason = match.groups()
        grouped_row_warnings.setdefault(reason, []).append(row_number)

    for reason, row_numbers in grouped_row_warnings.items():
        if len(row_numbers) == 1:
            compact_warnings.append(f"Skipped KSBIT row {row_numbers[0]}: {reason}")
            continue
        sample_rows = ", ".join(row_numbers[:10])
        if len(row_numbers) > 10:
            sample_rows = f"{sample_rows}, ..."
        compact_warnings.append(
            f"Skipped {len(row_numbers)} KSBIT rows: {reason}. "
            f"Example rows: {sample_rows}"
        )

    return compact_warnings


def _record_row_number(raw_record: Mapping[str, Any], fallback: int) -> int:
    row_number = raw_record.get(INTERNAL_ROW_NUMBER_FIELD)
    try:
        return int(str(row_number))
    except (TypeError, ValueError):
        return fallback


def _find_xlsx_headers(worksheet: Any) -> tuple[int, list[str]]:
    for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
        if _row_is_empty(row):
            continue
        headers = [
            _text_value(value) or f"Column {column_number}"
            for column_number, value in enumerate(row, start=1)
        ]
        return row_number, _dedupe_headers(headers)
    raise KsbitExportSourceError("KSBIT Excel export has no header row")


def _dedupe_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    deduped: list[str] = []
    for header in headers:
        normalized = _normalize_key(header)
        seen[normalized] = seen.get(normalized, 0) + 1
        if seen[normalized] == 1:
            deduped.append(header)
            continue
        deduped.append(f"{header} {seen[normalized]}")
    return deduped


def _validate_xlsx_headers(headers: list[str], export_path: Path) -> None:
    normalized_headers = {_normalize_key(header) for header in headers}
    required_fields = ("title", "company", "description", "apply_url")
    missing_fields = [
        field
        for field in required_fields
        if not any(
            _normalize_key(alias) in normalized_headers
            for alias in FIELD_ALIASES[field]
        )
    ]
    if missing_fields:
        raise KsbitExportSourceError(
            "KSBIT Excel export is missing required header(s): "
            f"{', '.join(missing_fields)}: {export_path}"
        )


def _row_is_empty(row: tuple[Any, ...]) -> bool:
    return all(_text_value(value) is None for value in row)


def _raw_payload_for_metadata(raw_record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _safe_metadata_value(value)
        for key, value in raw_record.items()
        if not _is_internal_field(key) and not _is_sensitive_analytics_field(key)
    }


def _is_internal_field(key: Any) -> bool:
    return str(key) in {INTERNAL_ROW_NUMBER_FIELD, INTERNAL_SOURCE_FORMAT_FIELD}


def _is_sensitive_analytics_field(key: Any) -> bool:
    return _normalize_key(str(key)) in SENSITIVE_ANALYTICS_FIELDS


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


def _format_location(value: Any, *, location_type: Any = None) -> str:
    location_type_text = _text_value(location_type)
    if location_type_text and "remote" in location_type_text.casefold():
        return "Remote"

    text = _text_value(value)
    if text is None:
        return DEFAULT_LOCATION

    parsed_location = _parse_location_json(text)
    return parsed_location or text


def _parse_location_json(text: str) -> str | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, list):
        locations = [
            location
            for item in payload
            if (location := _location_from_mapping(item)) is not None
        ]
        return "; ".join(dict.fromkeys(locations)) or None

    return _location_from_mapping(payload)


def _location_from_mapping(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None

    city_name = _text_value(value.get("CityName"))
    if city_name:
        parsed_city = _format_city_name(city_name)
        if parsed_city:
            return parsed_city

    city = _text_value(value.get("City"))
    state = _text_value(value.get("StateName") or value.get("RegionName"))
    country = _text_value(value.get("CountryName"))
    if city and state:
        return f"{city}, {state}"
    if city:
        return city
    return country


def _format_city_name(value: str) -> str | None:
    city, separator, state = value.rpartition(" - ")
    if separator and city.strip() and state.strip():
        return f"{city.strip()}, {state.strip()}"
    return value.strip() or None


def _clean_description(value: Any) -> str | None:
    text = _text_value(value)
    if text is None:
        return None

    text = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", text)
    text = re.sub(r"(?i)</\s*(p|li|div|tr|h[1-6])\s*>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _resolve_opt_cpt_flag(mapped: Mapping[str, Any]) -> bool | None:
    direct_value = _bool_value(mapped.get("opt_cpt_flag"))
    if direct_value is not None:
        return direct_value

    requirement = _text_value(mapped.get("work_authorization_requirement"))
    other_requirement = _text_value(mapped.get("other_work_authorization"))
    combined_text = " ".join(
        value for value in (requirement, other_requirement) if value is not None
    )
    if not combined_text:
        return None

    normalized = combined_text.casefold()
    if (
        "all work authorizations accepted" in normalized
        or "stem eligible degree" in normalized
    ):
        return True
    if (
        "permanent us work authorization required" in normalized
        or "u.s. citizen" in normalized
        or "us citizen" in normalized
        or "green card" in normalized
        or "permanent resident" in normalized
    ):
        return False
    return None


def _parse_posted_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

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
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if text.casefold() in {"null", "none", "nan"}:
        return None
    return text or None


def _safe_metadata_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text_value(value)
    if text is None:
        return None
    return value


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := _text_value(item)) is not None]
    text = _text_value(value)
    if text is None:
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

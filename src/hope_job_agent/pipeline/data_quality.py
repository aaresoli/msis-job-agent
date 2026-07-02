"""Deterministic data-quality reporting for normalized job postings.

The report is intentionally rule-based and free of any LLM inference so it can
be shown to KSBIT/GCS to explain the quality of an approved export. It reports
required-field coverage, common quality issues, and simple distributions.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hope_job_agent.classification.classifier import FALLBACK_ROLE
from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.ksbit_export import DEFAULT_LOCATION

DEFAULT_SHORT_DESCRIPTION_CHARS = 200
DEFAULT_STALE_AFTER_DAYS = 90
DEFAULT_EXAMPLE_LIMIT = 10

DEFAULT_THRESHOLDS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "data_quality_thresholds.json"
)


class DataQualityThresholdsError(ValueError):
    """Raised when a data-quality thresholds config file is invalid."""


@dataclass(frozen=True)
class DataQualityThresholds:
    """Documented, overridable thresholds for the data-quality report.

    Defaults are deliberate proxies (a description under ~200 chars is thin for
    matching; a posting older than ~90 days is likely stale) and are expected to
    be tuned once GCS confirms what matters for their workflow.
    """

    short_description_chars: int = DEFAULT_SHORT_DESCRIPTION_CHARS
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
    example_limit: int = DEFAULT_EXAMPLE_LIMIT


DEFAULT_DATA_QUALITY_THRESHOLDS = DataQualityThresholds()


def load_data_quality_thresholds(
    path: str | Path = DEFAULT_THRESHOLDS_PATH,
) -> DataQualityThresholds:
    """Load and validate a data-quality thresholds config file."""

    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataQualityThresholdsError(
            f"Data-quality thresholds config is not valid JSON: {config_path}: "
            f"{exc.msg}"
        ) from exc
    except OSError as exc:
        raise DataQualityThresholdsError(
            f"Data-quality thresholds config could not be read: {config_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise DataQualityThresholdsError(
            f"Data-quality thresholds config must be a JSON object: {config_path}"
        )

    allowed = {field.name for field in fields(DataQualityThresholds)}
    extra = sorted(set(payload) - allowed)
    if extra:
        raise DataQualityThresholdsError(
            f"Data-quality thresholds config has unknown keys: extra={extra}"
        )

    merged = {**DEFAULT_DATA_QUALITY_THRESHOLDS.__dict__, **payload}
    try:
        return DataQualityThresholds(
            short_description_chars=int(merged["short_description_chars"]),
            stale_after_days=int(merged["stale_after_days"]),
            example_limit=int(merged["example_limit"]),
        )
    except (TypeError, ValueError) as exc:
        raise DataQualityThresholdsError(
            f"Data-quality thresholds must be integers: {config_path}: {exc}"
        ) from exc


# Fields checked for completeness. Required fields are always present on a valid
# JobPosting, but they are still reported so the coverage table is complete.
_COMPLETENESS_FIELDS = (
    "title",
    "company",
    "location",
    "description",
    "url",
    "posted_date",
    "employment_type",
    "seniority",
    "source_job_id",
    "opt_cpt_flag",
)


@dataclass(frozen=True)
class _Issue:
    """A single data-quality issue: a count plus a few example job ids."""

    key: str
    description: str
    predicate_field: str


def build_data_quality_report(
    jobs: Sequence[JobPosting],
    *,
    raw_count: int | None = None,
    duplicate_count: int | None = None,
    adapter_warnings: Sequence[str] | None = None,
    now: date | None = None,
    short_description_chars: int = DEFAULT_SHORT_DESCRIPTION_CHARS,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    example_limit: int = DEFAULT_EXAMPLE_LIMIT,
) -> dict[str, Any]:
    """Build a structured, deterministic data-quality report for ``jobs``.

    Args:
        jobs: Normalized (and ideally classified) postings to inspect.
        raw_count: Optional count of raw source rows before validation.
        duplicate_count: Optional count of duplicates removed upstream.
        adapter_warnings: Optional adapter-level warnings to surface verbatim.
        now: Reference date for staleness checks. Defaults to today (UTC).
        short_description_chars: Descriptions shorter than this are flagged.
        stale_after_days: Postings older than this many days are flagged.
        example_limit: Max example job ids recorded per issue.
    """

    reference_date = now or datetime.now(UTC).date()
    total = len(jobs)

    issue_counts: dict[str, int] = {}
    issue_examples: dict[str, list[str]] = {}

    def _flag(job: JobPosting, key: str) -> None:
        issue_counts[key] = issue_counts.get(key, 0) + 1
        examples = issue_examples.setdefault(key, [])
        if len(examples) < example_limit:
            examples.append(_job_identifier(job))

    completeness_present: Counter[str] = Counter()

    for job in jobs:
        for field in _COMPLETENESS_FIELDS:
            if _field_is_present(job, field):
                completeness_present[field] += 1

        if not _location_is_specific(job.location):
            _flag(job, "missing_location")
        if job.posted_date is None:
            _flag(job, "missing_posted_date")
        elif _is_stale(job.posted_date, reference_date, stale_after_days):
            _flag(job, "stale_posting")
        if len(job.description.strip()) < short_description_chars:
            _flag(job, "short_description")
        if not _is_valid_http_url(job.url):
            _flag(job, "invalid_url")
        if job.opt_cpt_flag is None:
            _flag(job, "unknown_opt_cpt")
        if not job.role_tags or job.role_tags == [FALLBACK_ROLE]:
            _flag(job, "unclassified_role")
        if not job.concentration_tags:
            _flag(job, "unclassified_concentration")
        if bool(job.raw_metadata.get("source_job_id_was_generated")):
            _flag(job, "generated_source_job_id")

    completeness = {
        field: {
            "present": completeness_present[field],
            "missing": total - completeness_present[field],
            "present_pct": _pct(completeness_present[field], total),
        }
        for field in _COMPLETENESS_FIELDS
    }

    issues = [
        {
            "key": key,
            "description": description,
            "count": issue_counts.get(key, 0),
            "example_job_ids": issue_examples.get(key, []),
        }
        for key, description in _ISSUE_DESCRIPTIONS.items()
    ]

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_date": reference_date.isoformat(),
        "thresholds": {
            "short_description_chars": short_description_chars,
            "stale_after_days": stale_after_days,
        },
        "totals": {
            "raw_count": raw_count,
            "job_count": total,
            "duplicate_count": duplicate_count,
        },
        "overall_completeness_pct": _overall_completeness_pct(
            completeness_present, total
        ),
        "field_completeness": completeness,
        "issues": issues,
        "distributions": {
            "by_source": _count_field(jobs, "source"),
            "by_employment_type": _count_optional_field(jobs, "employment_type"),
            "by_seniority": _count_optional_field(jobs, "seniority"),
            "by_role_tag": _count_tags(jobs, "role_tags"),
            "by_concentration_tag": _count_tags(jobs, "concentration_tags"),
            "opt_cpt": _count_opt_cpt(jobs),
        },
        "adapter_warnings": list(adapter_warnings or []),
    }
    return report


_ISSUE_DESCRIPTIONS: dict[str, str] = {
    "missing_location": "Location is missing or set to the default placeholder.",
    "missing_posted_date": "No parseable posted date was provided by the source.",
    "stale_posting": "Posting is older than the staleness threshold.",
    "short_description": "Description is suspiciously short for matching.",
    "invalid_url": "Apply/post URL is not a valid http(s) URL.",
    "unknown_opt_cpt": "OPT/CPT eligibility could not be determined.",
    "unclassified_role": "No confident MSIS target role was assigned.",
    "unclassified_concentration": "No MSIS concentration tag was assigned.",
    "generated_source_job_id": (
        "Source did not provide a stable job id (one was generated)."
    ),
}


def _job_identifier(job: JobPosting) -> str:
    return job.source_job_id or job.url


def _field_is_present(job: JobPosting, field: str) -> bool:
    value = getattr(job, field, None)
    if field == "location":
        return _location_is_specific(value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _location_is_specific(location: Any) -> bool:
    if not isinstance(location, str):
        return False
    text = location.strip()
    return bool(text) and text.casefold() != DEFAULT_LOCATION.casefold()


def _is_stale(posted_date: date, reference_date: date, stale_after_days: int) -> bool:
    return (reference_date - posted_date).days > stale_after_days


def _is_valid_http_url(url: str) -> bool:
    parsed = urlsplit(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(100 * numerator / denominator, 1)


def _overall_completeness_pct(present: Counter[str], total: int) -> float:
    if total == 0:
        return 0.0
    possible = total * len(_COMPLETENESS_FIELDS)
    return _pct(sum(present.values()), possible)


def _count_field(jobs: Sequence[JobPosting], field: str) -> dict[str, int]:
    counter = Counter(str(getattr(job, field)) for job in jobs)
    return _sorted_counts(counter)


def _count_optional_field(jobs: Sequence[JobPosting], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for job in jobs:
        value = getattr(job, field, None)
        label = value.strip() if isinstance(value, str) and value.strip() else "Unknown"
        counter[label] += 1
    return _sorted_counts(counter)


def _count_tags(jobs: Sequence[JobPosting], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for job in jobs:
        tags = getattr(job, field, []) or []
        if not tags:
            counter["Unclassified"] += 1
            continue
        for tag in tags:
            counter[tag] += 1
    return _sorted_counts(counter)


def _count_opt_cpt(jobs: Sequence[JobPosting]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for job in jobs:
        if job.opt_cpt_flag is True:
            counter["friendly"] += 1
        elif job.opt_cpt_flag is False:
            counter["not_friendly"] += 1
        else:
            counter["unknown"] += 1
    return _sorted_counts(counter)


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))

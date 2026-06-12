"""Approved local JSON export adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


class ApprovedJsonSourceError(ValueError):
    """Raised when an approved JSON export cannot be loaded safely."""


@dataclass(frozen=True)
class ApprovedJsonFetchResult:
    """Jobs loaded from an approved export plus recoverable record warnings."""

    jobs: list[JobPosting]
    raw_count: int
    warnings: list[str]


class ApprovedSourceMetadata(BaseModel):
    """Approval metadata required for local source exports."""

    source_name: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approval_date: date
    access_method: str = Field(min_length=1)
    terms_reviewed: bool = True
    source_owner: str | None = None
    documentation_url: str | None = None

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @field_validator("terms_reviewed")
    @classmethod
    def require_terms_review(cls, value: bool) -> bool:
        """Require documented terms review before treating an export as approved."""

        if not value:
            raise ValueError("terms_reviewed must be true for approved exports")
        return value


class ApprovedJsonJobRecord(BaseModel):
    """Raw job record from an approved JSON export."""

    source_job_id: str | None = None
    title: str
    company: str
    location: str
    description: str
    url: str | None = None
    apply_url: str | None = None
    post_url: str | None = None
    source: str | None = None
    posted_date: date | None = None
    employment_type: str | None = None
    seniority: str | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    opt_cpt_flag: bool | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def require_url(self) -> ApprovedJsonJobRecord:
        """Require one post/apply URL field for downstream ranking output."""

        if not (self.url or self.apply_url or self.post_url):
            raise ValueError("one of url, apply_url, or post_url is required")
        return self

    def to_job_posting(self, default_source: str) -> JobPosting:
        """Convert an export record into the shared job posting model."""

        source = self.source.strip() if self.source and self.source.strip() else ""
        metadata = dict(self.raw_metadata)
        if self.source_job_id:
            metadata["source_job_id"] = self.source_job_id
        if self.model_extra:
            metadata.update(self.model_extra)
        return JobPosting(
            source=source or default_source,
            source_job_id=self.source_job_id,
            title=self.title,
            company=self.company,
            location=self.location,
            description=self.description,
            url=self.url or self.apply_url or self.post_url or "",
            posted_date=self.posted_date,
            employment_type=self.employment_type,
            seniority=self.seniority,
            concentration_tags=self.concentration_tags,
            role_tags=self.role_tags,
            opt_cpt_flag=self.opt_cpt_flag,
            raw_metadata=metadata,
        )


class ApprovedJsonExport(BaseModel):
    """Top-level approved JSON export envelope."""

    metadata: ApprovedSourceMetadata
    jobs: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class ApprovedJsonJobSource(BaseJobSource):
    """Read approved local JSON job exports without live collection."""

    source_name = "approved_json"

    def __init__(self, export_path: str | Path) -> None:
        """Create an adapter for a local approved JSON export."""

        self.export_path = Path(export_path)

    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch jobs from a local approved JSON export."""

        return self.fetch_jobs_with_warnings().jobs

    def fetch_jobs_with_warnings(self) -> ApprovedJsonFetchResult:
        """Fetch jobs while skipping malformed individual records when possible."""

        export = self._load_export()
        self.source_name = export.metadata.source_name
        jobs: list[JobPosting] = []
        warnings: list[str] = []

        for index, raw_record in enumerate(export.jobs, start=1):
            try:
                record = ApprovedJsonJobRecord.model_validate(raw_record)
                jobs.append(
                    record.to_job_posting(default_source=export.metadata.source_name)
                )
            except ValidationError as exc:
                warnings.append(
                    "Skipped malformed job record "
                    f"{index} in {self.export_path}: {_summarize_validation_error(exc)}"
                )

        return ApprovedJsonFetchResult(
            jobs=jobs,
            raw_count=len(export.jobs),
            warnings=warnings,
        )

    def health_check(self) -> bool:
        """Return whether the local export can be loaded and validated."""

        try:
            self._load_export()
        except ApprovedJsonSourceError:
            return False
        return True

    def _load_export(self) -> ApprovedJsonExport:
        """Load and validate the approved JSON export envelope."""

        payload = self._read_payload()
        try:
            return ApprovedJsonExport.model_validate(payload)
        except ValidationError as exc:
            raise ApprovedJsonSourceError(
                f"Approved JSON export failed validation: {self.export_path}: {exc}"
            ) from exc

    def _read_payload(self) -> Any:
        """Read JSON data from disk with clear source-specific errors."""

        try:
            raw_payload = self.export_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ApprovedJsonSourceError(
                f"Approved JSON export not found: {self.export_path}"
            ) from exc
        except OSError as exc:
            raise ApprovedJsonSourceError(
                f"Approved JSON export could not be read: {self.export_path}: {exc}"
            ) from exc

        try:
            return json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ApprovedJsonSourceError(
                f"Approved JSON export is not valid JSON: "
                f"{self.export_path}: {exc.msg}"
            ) from exc


def _summarize_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    first_error = errors[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    message = first_error.get("msg", str(exc))
    return f"{location}: {message}" if location else str(message)

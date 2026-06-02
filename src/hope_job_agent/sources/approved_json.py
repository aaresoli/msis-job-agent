"""Approved local JSON export adapter."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource


class ApprovedJsonSourceError(ValueError):
    """Raised when an approved JSON export cannot be loaded safely."""


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

    title: str
    company: str
    location: str
    description: str
    url: str
    source: str | None = None
    posted_date: date | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    opt_cpt_flag: bool | None = None

    model_config = ConfigDict(extra="ignore")

    def to_job_posting(self, default_source: str) -> JobPosting:
        """Convert an export record into the shared job posting model."""

        source = self.source.strip() if self.source and self.source.strip() else ""
        return JobPosting(
            source=source or default_source,
            title=self.title,
            company=self.company,
            location=self.location,
            description=self.description,
            url=self.url,
            posted_date=self.posted_date,
            concentration_tags=self.concentration_tags,
            opt_cpt_flag=self.opt_cpt_flag,
        )


class ApprovedJsonExport(BaseModel):
    """Top-level approved JSON export envelope."""

    metadata: ApprovedSourceMetadata
    jobs: list[ApprovedJsonJobRecord] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class ApprovedJsonJobSource(BaseJobSource):
    """Read approved local JSON job exports without live collection."""

    source_name = "approved_json"

    def __init__(self, export_path: str | Path) -> None:
        """Create an adapter for a local approved JSON export."""

        self.export_path = Path(export_path)

    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch jobs from a local approved JSON export."""

        export = self._load_export()
        self.source_name = export.metadata.source_name
        return [
            record.to_job_posting(default_source=export.metadata.source_name)
            for record in export.jobs
        ]

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

"""Configuration models and loader for the company_careers source.

The company target list is intentionally kept in a config file (YAML or JSON)
rather than in code, so Graduate Career Services can add, disable, or reprioritize
employers without editing Python. See ``config/company_careers.yml`` for the
shipped sample and ``docs/company_careers.md`` for how to add a company.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("config/company_careers.yml")

# Providers with an implemented adapter. "static" is a placeholder for companies
# whose careers page cannot yet be fetched compliantly; such targets should be
# marked ``enabled: false`` until an adapter exists.
KNOWN_PROVIDERS = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "workday",
        "oraclecloud",
        "icims",
        "static",
    }
)

# Lifecycle of an employer entry's endpoint verification (see docs/company_careers.md):
#   verified    - a public endpoint was confirmed live (low-volume request).
#   pending     - a candidate endpoint exists but has not been confirmed yet.
#   unsupported - no compliant public endpoint exists; entry stays disabled with
#                 an explicit ``unsupported_reason``.
VERIFICATION_STATUSES = frozenset({"verified", "pending", "unsupported"})


class FetchPolicy(BaseModel):
    """Politeness and volume limits shared by every company fetch."""

    user_agent: str = (
        "KelleyHOPE-MSIS-JobAgent/0.1 "
        "(+https://kelley.iu.edu; compliant public career-page reader)"
    )
    min_interval_seconds: float = Field(default=1.0, ge=0.0)
    timeout_seconds: float = Field(default=15.0, gt=0.0)
    max_retries: int = Field(default=2, ge=0)
    backoff_seconds: float = Field(default=0.5, ge=0.0)
    max_jobs_per_company: int = Field(default=200, ge=1)
    max_total_jobs_per_run: int = Field(default=2000, ge=1)
    respect_robots: bool = True
    # Some ATS list endpoints omit the full description; fetching detail pages
    # improves relevance scoring but increases request volume.
    fetch_descriptions: bool = True

    model_config = ConfigDict(extra="forbid")


class CompanyTarget(BaseModel):
    """One configured employer career source."""

    company_name: str = Field(min_length=1)
    ats_provider: str = Field(min_length=1)
    careers_url: str | None = None
    # Board token (Greenhouse), site (Lever), job-board name (Ashby), or company
    # identifier (SmartRecruiters). Workday uses tenant/site/host below instead.
    ats_slug: str | None = None
    tenant: str | None = None
    site: str | None = None
    host: str | None = None
    enabled: bool = True
    priority: int = Field(default=100, ge=0)
    country_filters: list[str] = Field(default_factory=list)
    location_filters: list[str] = Field(default_factory=list)
    # Optional workplace filter, e.g. ["remote", "hybrid"]. Empty = no filter.
    workplace_filters: list[str] = Field(default_factory=list)
    relevant_keywords_override: list[str] | None = None
    notes: str | None = None
    compliance_review: str | None = None
    # Structured coverage metadata sourced from the MSIS LAMP list and the
    # endpoint-verification workflow (scripts/research_lamp_companies.py).
    student_interest_rank: int | None = Field(default=None, ge=1)
    student_interest_count: int | None = Field(default=None, ge=0)
    # Excel ranks whose rows are duplicate aliases of this entry (e.g. rank
    # 110 "TCS" merged into rank 78 "Tata Consultancy Services"). Lets the
    # coverage math account for every Excel rank without duplicate entries.
    merged_excel_ranks: list[int] = Field(default_factory=list)
    industry: str | None = None
    verification_status: str = "pending"
    verified_at: str | None = None
    verification_source_url: str | None = None
    unsupported_reason: str | None = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("ats_provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("verification_status")
    @classmethod
    def _validate_verification_status(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in VERIFICATION_STATUSES:
            allowed = ", ".join(sorted(VERIFICATION_STATUSES))
            raise ValueError(
                f"verification_status must be one of: {allowed} (got '{value}')"
            )
        return normalized

    @model_validator(mode="after")
    def _check_verification_consistency(self) -> "CompanyTarget":
        # Ranked LAMP-list employers (student_interest_rank set) must be either
        # enabled with a verified endpoint or disabled with an explicit status.
        if (
            self.student_interest_rank is not None
            and self.enabled
            and self.verification_status != "verified"
        ):
            raise ValueError(
                f"'{self.company_name}' is enabled but verification_status is "
                f"'{self.verification_status}'. Enabled ranked companies must "
                "have a verified public endpoint."
            )
        if self.verification_status == "unsupported" and not self.unsupported_reason:
            raise ValueError(
                f"'{self.company_name}' is marked unsupported but has no "
                "unsupported_reason."
            )
        return self

    @property
    def provider_is_known(self) -> bool:
        """Return whether an adapter exists for this provider."""

        return self.ats_provider in KNOWN_PROVIDERS


class CompanyCareersConfig(BaseModel):
    """Top-level company_careers configuration."""

    fetch_policy: FetchPolicy = Field(default_factory=FetchPolicy)
    relevance_threshold: int = 3
    companies: list[CompanyTarget] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _reject_duplicate_enabled_endpoints(self) -> "CompanyCareersConfig":
        """Alias entries must not cause two runtime fetches of one board."""

        seen: dict[tuple[str, str, str, str, str], str] = {}
        for company in self.companies:
            if not company.enabled:
                continue
            key = (
                company.ats_provider,
                (company.ats_slug or "").casefold(),
                (company.host or "").casefold(),
                (company.tenant or "").casefold(),
                (company.site or "").casefold(),
            )
            if key in seen:
                raise ValueError(
                    f"Duplicate enabled ATS endpoint: '{company.company_name}' "
                    f"and '{seen[key]}' both target {key}. Disable one (alias "
                    "duplicates must not double-fetch a board)."
                )
            seen[key] = company.company_name
        return self

    def enabled_companies(self) -> list[CompanyTarget]:
        """Return enabled companies sorted by ascending priority then name."""

        enabled = [company for company in self.companies if company.enabled]
        return sorted(
            enabled, key=lambda company: (company.priority, company.company_name)
        )


class CompanyCareersConfigError(ValueError):
    """Raised when the company_careers config cannot be loaded."""


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CompanyCareersConfigError(f"Company config not found: {path}")
    if not path.is_file():
        raise CompanyCareersConfigError(f"Company config path is not a file: {path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.casefold()
    if suffix in {".yml", ".yaml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise CompanyCareersConfigError(
                "Reading YAML company configs requires PyYAML. Install pyyaml, or "
                "use a .json config instead."
            ) from exc
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise CompanyCareersConfigError(
                f"Company config is not valid YAML: {path}: {exc}"
            ) from exc
    elif suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CompanyCareersConfigError(
                f"Company config is not valid JSON: {path}: {exc.msg}"
            ) from exc
    else:
        raise CompanyCareersConfigError(
            f"Unsupported company config extension '{path.suffix}'. Use .yml or .json."
        )

    if not isinstance(payload, dict):
        raise CompanyCareersConfigError(
            "Company config must be a mapping with 'companies' and optional "
            "'fetch_policy'/'relevance_threshold' keys."
        )
    return payload


def load_company_careers_config(
    path: str | Path | None = None,
) -> CompanyCareersConfig:
    """Load and validate the company_careers config from YAML or JSON."""

    resolved = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    payload = _load_raw(resolved)
    try:
        config = CompanyCareersConfig.model_validate(payload)
    except ValueError as exc:
        raise CompanyCareersConfigError(
            f"Company config failed validation: {resolved}: {exc}"
        ) from exc
    return config

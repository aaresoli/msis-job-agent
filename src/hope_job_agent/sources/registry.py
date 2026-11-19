"""Source registry and compliance guardrails."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hope_job_agent.sources.base import BaseJobSource


class SourceStatus(StrEnum):
    """Compliance status for a source adapter."""

    APPROVED = "approved"
    RESTRICTED = "restricted"
    MANUAL_REFERENCE = "manual_reference"
    DISABLED = "disabled"


class SourceComplianceError(RuntimeError):
    """Raised when a source is not allowed to run."""


@dataclass(frozen=True)
class SourceMetadata:
    """Registry metadata for one source adapter."""

    name: str
    display_name: str
    status: SourceStatus
    source_type: str
    access_method: str
    priority: int
    notes: str


SOURCE_REGISTRY: dict[str, SourceMetadata] = {
    "approved_json": SourceMetadata(
        name="approved_json",
        display_name="Approved Local JSON Export",
        status=SourceStatus.APPROVED,
        source_type="local_export",
        access_method="Approved public/manual export fixture",
        priority=1,
        notes="Safe v0 source for local development and demos.",
    ),
    "employer_careers": SourceMetadata(
        name="employer_careers",
        display_name="Employer Careers Sample",
        status=SourceStatus.APPROVED,
        source_type="sample_employer_careers",
        access_method="Realistic local fixture only; no live collection.",
        priority=2,
        notes="Prototype source shape for future ATS/API integrations.",
    ),
    "company_careers": SourceMetadata(
        name="company_careers",
        display_name="Company Careers (Public ATS Job Boards)",
        status=SourceStatus.APPROVED,
        source_type="company_careers",
        access_method=(
            "Public employer career pages and public ATS APIs only "
            "(Greenhouse, Lever, Ashby, SmartRecruiters, Workday). Rate limited, "
            "clear User-Agent, robots.txt respected. No login/CAPTCHA/proxy "
            "circumvention and no LinkedIn/Handshake collection."
        ),
        priority=2,
        notes=(
            "Config-driven employer list in config/company_careers.yml. Stores "
            "provider payloads in raw_metadata; auto-disables sources that block "
            "the crawler."
        ),
    ),
    "ksbit_export": SourceMetadata(
        name="ksbit_export",
        display_name="KSBIT / 12Twenty Local Export",
        status=SourceStatus.APPROVED,
        source_type="local_export",
        access_method=(
            "Approved local JSON/CSV/XLSX export only; no live collection, "
            "credentials, or browser automation."
        ),
        priority=3,
        notes=(
            "Preserves source row context in raw_metadata while excluding "
            "application/applicant analytics fields."
        ),
    ),
    "kelleylink_excel": SourceMetadata(
        name="kelleylink_excel",
        display_name="KelleyLink / 12Twenty Excel Export",
        status=SourceStatus.APPROVED,
        source_type="local_export",
        access_method=(
            "Approved local 12Twenty/KelleyLink JSON/CSV/XLSX export only; no "
            "live collection, credentials, or browser automation."
        ),
        priority=3,
        notes=(
            "Friendly alias of ksbit_export for the KelleyLink/12Twenty demo "
            "command. Uses the identical local-export adapter."
        ),
    ),
    "handshake": SourceMetadata(
        name="handshake",
        display_name="Handshake",
        status=SourceStatus.RESTRICTED,
        source_type="restricted_platform",
        access_method="Official API/export approval required before use.",
        priority=99,
        notes="Do not scrape or automate login workflows.",
    ),
    "linkedin_reference": SourceMetadata(
        name="linkedin_reference",
        display_name="LinkedIn Reference",
        status=SourceStatus.MANUAL_REFERENCE,
        source_type="restricted_reference",
        access_method="Manual/reference-only unless an approved method exists.",
        priority=99,
        notes="Do not scrape LinkedIn or automate login workflows.",
    ),
    "ksbit_denodo": SourceMetadata(
        name="ksbit_denodo",
        display_name="KSBIT Denodo API",
        status=SourceStatus.DISABLED,
        source_type="institutional_api",
        access_method="Approved Denodo view and service credentials required.",
        priority=3,
        notes="Contract only; enable after the view schema and endpoint are approved.",
    ),
    "apify_linkedin": SourceMetadata(
        name="apify_linkedin",
        display_name="Apify LinkedIn Jobs",
        status=SourceStatus.APPROVED,
        source_type="third_party_collection",
        access_method=(
            "Apify API v2 with the user-supplied account token. Reads datasets "
            "of completed actor runs by default; new (paid) actor runs are "
            "user-invoked only via --apify-trigger-run. No direct LinkedIn "
            "collection happens in this codebase."
        ),
        priority=2,
        notes=(
            "Approved for the faculty demo using the project owner's Apify "
            "account and LinkedIn jobs scraper actor. Token lives in .env as "
            "APIFY_TOKEN and is never committed."
        ),
    ),
    "apify_linkedin_posts": SourceMetadata(
        name="apify_linkedin_posts",
        display_name="Apify LinkedIn Posts",
        status=SourceStatus.APPROVED,
        source_type="third_party_collection",
        access_method=(
            "Apify API v2 with the user-supplied account token. Reads datasets "
            "of completed actor runs by default; new (paid) actor runs are "
            "user-invoked only via --apify-trigger-run. Produces hiring-manager "
            "'market posts' rather than job listings. No direct LinkedIn "
            "collection happens in this codebase."
        ),
        priority=2,
        notes=(
            "Approved for the faculty demo using the project owner's Apify "
            "account and LinkedIn posts scraper actor. Reuses APIFY_TOKEN; the "
            "posts actor id lives in .env as APIFY_POSTS_ACTOR_ID. Posts are "
            "gated with the same deterministic MSIS relevance filter as jobs."
        ),
    ),
}


def get_source_metadata(source_name: str) -> SourceMetadata:
    """Return metadata for a registered source."""

    try:
        return SOURCE_REGISTRY[source_name]
    except KeyError as exc:
        raise SourceComplianceError(
            f"Source '{source_name}' is not registered. Add registry metadata "
            "before running it."
        ) from exc


def ensure_source_allowed(source_name: str) -> SourceMetadata:
    """Return metadata if a source is approved to run."""

    metadata = get_source_metadata(source_name)
    if metadata.status is not SourceStatus.APPROVED:
        raise SourceComplianceError(
            f"Source '{source_name}' is {metadata.status.value} and cannot run "
            f"without documented approval. Notes: {metadata.notes}"
        )
    return metadata


def create_source_adapter(
    source_name: str,
    input_path: str | Path,
    *,
    source_since_date: str | None = None,
    source_limit: int | None = None,
) -> BaseJobSource:
    """Construct an approved local-file source adapter by registry name."""

    ensure_source_allowed(source_name)

    if source_name == "approved_json":
        if source_since_date is not None or source_limit is not None:
            raise SourceComplianceError(
                "--source-since-date and --source-limit are only supported for "
                "ksbit_export"
            )
        from hope_job_agent.sources.approved_json import ApprovedJsonJobSource

        return ApprovedJsonJobSource(input_path)

    if source_name in {"ksbit_export", "kelleylink_excel"}:
        from hope_job_agent.sources.ksbit_export import KsbitExportSource

        return KsbitExportSource(
            input_path,
            since_date=source_since_date,
            limit=source_limit,
        )

    if source_name == "company_careers":
        if source_since_date is not None or source_limit is not None:
            raise SourceComplianceError(
                "--source-since-date and --source-limit are only supported for "
                "ksbit_export"
            )
        from hope_job_agent.sources.company_careers import CompanyCareersSource

        # For company_careers the input path is the YAML/JSON company config.
        return CompanyCareersSource(config_path=input_path)

    raise SourceComplianceError(
        f"Source '{source_name}' is registered but cannot be constructed from a "
        "local input file by this pipeline. Supported local sources: "
        "approved_json, ksbit_export, kelleylink_excel, company_careers."
    )

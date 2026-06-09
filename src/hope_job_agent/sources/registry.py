"""Source registry and compliance guardrails."""

from dataclasses import dataclass
from enum import StrEnum


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

"""Centralized deduplication helpers shared by pipeline and persistence."""

from __future__ import annotations

from hope_job_agent.models.job import JobPosting
from hope_job_agent.utils.hashing import stable_hash
from hope_job_agent.utils.url import canonicalize_url as normalize_url

# Backward-compatible alias used in tests and docs.
canonicalize_url = normalize_url


def canonicalize_job_url(job: JobPosting) -> str | None:
    """Return canonical URL identity for a job when available."""

    url = str(getattr(job, "url", "") or "").strip()
    if not url:
        apply_url = str(getattr(job, "apply_url", "") or "").strip()
        if not apply_url:
            return None
        url = apply_url
    return normalize_url(url)


def normalize_company_name(name: str | None) -> str:
    """Normalize a company name for deduplication and lookup."""

    return " ".join(str(name or "").split()).casefold()


def normalize_title(title: str | None) -> str:
    """Normalize a job title for deduplication and lookup."""

    return " ".join(str(title or "").split()).casefold()


def normalize_location(location: str | None) -> str:
    """Normalize a job location for deduplication and lookup."""

    return " ".join(str(location or "").split()).casefold()


def compute_content_hash(job: JobPosting) -> str:
    """Return a stable hash of normalized job content."""

    description = " ".join(str(getattr(job, "description", "") or "").split())
    parts = [
        normalize_title(job.title),
        normalize_company_name(job.company),
        normalize_location(job.location),
        description.casefold(),
    ]
    return stable_hash("||".join(parts))


def compute_canonical_fingerprint(job: JobPosting) -> str:
    """Return a fingerprint for company + title + location + content hash."""

    return stable_hash(
        "||".join(
            [
                normalize_company_name(job.company),
                normalize_title(job.title),
                normalize_location(job.location),
                compute_content_hash(job),
            ]
        )
    )


def source_external_identity(job: JobPosting) -> tuple[str, str] | None:
    """Return (source, external_job_id) when the source provides an ID."""

    raw_metadata = getattr(job, "raw_metadata", {}) or {}
    value = getattr(job, "source_job_id", None) or raw_metadata.get("source_job_id")
    if value is None:
        return None
    normalized_value = str(value).strip()
    if not normalized_value:
        return None
    source = str(getattr(job, "source", "") or "").strip()
    if not source:
        return None
    return source, normalized_value


def url_identity(job: JobPosting) -> tuple[str, str] | None:
    """Return (company, apply_or_source_url) fallback identity."""

    canonical = canonicalize_job_url(job)
    if canonical is None:
        return None
    return normalize_company_name(job.company), canonical


def job_identity_keys(job: JobPosting) -> list[tuple[str, str]]:
    """Return ordered deduplication identity keys for a job."""

    keys: list[tuple[str, str]] = []
    external = source_external_identity(job)
    if external is not None:
        keys.append(("source_external", f"{external[0]}:{external[1].casefold()}"))
    canonical = canonicalize_job_url(job)
    if canonical is not None:
        keys.append(("canonical_url", canonical))
    keys.append(("content_hash", compute_content_hash(job)))
    keys.append(("fingerprint", compute_canonical_fingerprint(job)))
    url_pair = url_identity(job)
    if url_pair is not None:
        keys.append(("company_url", f"{url_pair[0]}:{url_pair[1]}"))
    return list(dict.fromkeys(keys))


__all__ = [
    "canonicalize_job_url",
    "canonicalize_url",
    "compute_canonical_fingerprint",
    "compute_content_hash",
    "job_identity_keys",
    "normalize_company_name",
    "normalize_location",
    "normalize_title",
    "normalize_url",
    "source_external_identity",
    "url_identity",
]

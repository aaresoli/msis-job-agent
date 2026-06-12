"""Deduplication helpers for normalized job postings."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.normalize import normalize_job
from hope_job_agent.utils.hashing import stable_hash

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def deduplicate_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    """Remove duplicate jobs while preserving first-seen order.

    Canonical URLs and source-provided job IDs are the strongest duplicate
    signals. A same title/company/location posting is considered a duplicate
    only when the normalized description hash also matches, which avoids
    collapsing distinct roles.
    """

    seen_urls: set[str] = set()
    seen_source_job_ids: set[tuple[str, str]] = set()
    seen_signatures: set[tuple[str, str, str, str]] = set()
    unique_jobs: list[JobPosting] = []

    for job in jobs:
        normalized_job = normalize_job(job)
        normalized_url = canonicalize_url(str(normalized_job.url))
        source_job_id = _source_job_id(normalized_job)
        signature = _job_signature(normalized_job)

        if normalized_url in seen_urls:
            continue
        if source_job_id and source_job_id in seen_source_job_ids:
            continue
        if signature in seen_signatures:
            continue

        seen_urls.add(normalized_url)
        if source_job_id:
            seen_source_job_ids.add(source_job_id)
        seen_signatures.add(signature)
        unique_jobs.append(normalized_job)

    return unique_jobs


def canonicalize_url(url: str) -> str:
    """Normalize URLs for duplicate detection."""

    parsed = urlsplit(url.strip())
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _job_signature(job: JobPosting) -> tuple[str, str, str, str]:
    return (
        job.title.casefold(),
        job.company.casefold(),
        job.location.casefold(),
        stable_hash(" ".join(job.description.casefold().split())),
    )


def _source_job_id(job: JobPosting) -> tuple[str, str] | None:
    value = job.source_job_id or job.raw_metadata.get("source_job_id")
    if value is None:
        return None
    normalized_value = str(value).strip()
    if not normalized_value:
        return None
    return (job.source.casefold(), normalized_value.casefold())

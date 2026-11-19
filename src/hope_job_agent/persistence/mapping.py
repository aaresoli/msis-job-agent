"""Row-to-model mapping shared by the workers and the scheduled ops tasks."""

from __future__ import annotations

from hope_job_agent.db.models import JobPostingRecord
from hope_job_agent.models.job import JobPosting


def job_from_record(record: JobPostingRecord) -> JobPosting:
    """Rebuild the normalized :class:`JobPosting` from its persisted row."""

    return JobPosting(
        source=record.source,
        source_job_id=record.external_job_id,
        title=record.title,
        company=record.company_name,
        location=record.location or "Not specified",
        description=record.description or "Description not supplied",
        url=(
            record.apply_url
            or record.source_url
            or record.canonical_url
            or f"https://unavailable.invalid/jobs/{record.id}"
        ),
        posted_date=record.posted_at,
        employment_type=record.employment_type,
        seniority=record.seniority,
        concentration_tags=record.concentration_tags or [],
        opt_cpt_flag=record.opt_cpt_flag,
        source_detail=record.source_detail,
        apply_url=record.apply_url,
        application_deadline=record.application_deadline,
        compensation=record.compensation,
        raw_metadata={"database_id": str(record.id)},
    )

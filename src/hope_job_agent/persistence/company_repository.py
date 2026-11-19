"""Company persistence repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.models import Company
from hope_job_agent.persistence.dedup import normalize_company_name


class CompanyRepository:
    """Canonical company lookup and creation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def normalize_company_name(name: str | None) -> str:
        return normalize_company_name(name)

    def get_or_create_company(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Company:
        """Return an existing company row or create a new one."""

        cleaned = " ".join(str(name or "").split())
        if not cleaned:
            raise ValueError("Company name is required")

        normalized = normalize_company_name(cleaned)
        existing = self._session.scalar(
            select(Company).where(Company.normalized_name == normalized)
        )
        if existing is not None:
            if metadata:
                self._apply_metadata(existing, metadata)
            return existing

        company = Company(
            name=cleaned,
            normalized_name=normalized,
            website_url=_optional_text(metadata, "website_url"),
            careers_url=_optional_text(metadata, "careers_url"),
            ats_provider=_optional_text(metadata, "ats_provider"),
            ats_slug=_optional_text(metadata, "ats_slug"),
            industry=_optional_text(metadata, "industry"),
            headquarters=_optional_text(metadata, "headquarters"),
        )
        self._session.add(company)
        self._session.flush()
        return company

    def _apply_metadata(self, company: Company, metadata: dict[str, Any]) -> None:
        for field in (
            "website_url",
            "careers_url",
            "ats_provider",
            "ats_slug",
            "industry",
            "headquarters",
        ):
            value = _optional_text(metadata, field)
            if value is not None:
                setattr(company, field, value)


def _optional_text(metadata: dict[str, Any] | None, key: str) -> str | None:
    if not metadata:
        return None
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None

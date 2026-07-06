"""iCIMS adapter interface (not yet implemented).

iCIMS does not expose a consistent, public JSON job-board API comparable to
Greenhouse/Lever/Ashby/SmartRecruiters. Fetching iCIMS-hosted postings
compliantly typically requires an employer-provisioned partner API or an
approved export, which is out of scope for this first version.

This module exists so the provider registry is complete and so companies using
iCIMS can be represented in config (with ``enabled: false``). If invoked, it
raises :class:`ProviderNotImplementedError` rather than shipping flaky scraping.
"""

from __future__ import annotations

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.http import HttpClient
from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    ProviderNotImplementedError,
    RawJob,
)


class ICIMSProvider(BaseProvider):
    name = "icims"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        return str(target.careers_url or "")

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        raise ProviderNotImplementedError(
            "iCIMS does not have a supported public JSON board API in this version. "
            f"Keep '{target.company_name}' disabled until an approved iCIMS partner "
            "API or export is available."
        )

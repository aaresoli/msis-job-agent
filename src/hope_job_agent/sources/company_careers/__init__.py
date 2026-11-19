"""Company/employer career-page source family (ATS-backed job boards).

This package fetches MSIS-relevant postings directly from public, employer-owned
career pages and public ATS job-board APIs (Greenhouse, Lever, Ashby,
SmartRecruiters, Workday). It normalizes them into the shared ``JobPosting``
model, filters/scores them for MSIS relevance, and feeds them into the same
downstream normalization, deduplication, classification, and ranking pipeline
used by the KelleyLink/KSBIT local-export source.

Compliance summary (see ``README.md`` and ``docs/compliance_notes.md``):

* Public employer career pages and public ATS APIs only.
* No LinkedIn/Handshake or any logged-in/account-gated collection.
* No CAPTCHA solving, login automation, proxy evasion, or access-control bypass.
* Respect robots.txt where applicable, rate limit, and send a clear User-Agent.
* Disable a source automatically if it blocks the crawler.
"""

from hope_job_agent.sources.company_careers.adapter import (
    COMPANY_CAREERS_SOURCE_NAME,
    CompanyCareersFetchResult,
    CompanyCareersSource,
    CompanyFetchReport,
)
from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfig,
    CompanyTarget,
    load_company_careers_config,
)

__all__ = [
    "COMPANY_CAREERS_SOURCE_NAME",
    "CompanyCareersConfig",
    "CompanyCareersFetchResult",
    "CompanyCareersSource",
    "CompanyFetchReport",
    "CompanyTarget",
    "load_company_careers_config",
]

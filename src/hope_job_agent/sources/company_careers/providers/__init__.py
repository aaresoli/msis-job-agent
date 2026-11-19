"""Provider-specific ATS adapters for the company_careers source.

Each module implements one public ATS job-board integration and returns a list
of provider-neutral :class:`RawJob` objects. Keeping parsing per provider (rather
than one giant function) makes each adapter small, deterministic, and testable
with mocked HTTP responses.
"""

from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    ProviderError,
    ProviderNotImplementedError,
    RawJob,
    clean_html,
    parse_date,
)

__all__ = [
    "BaseProvider",
    "ProviderError",
    "ProviderNotImplementedError",
    "RawJob",
    "clean_html",
    "parse_date",
]

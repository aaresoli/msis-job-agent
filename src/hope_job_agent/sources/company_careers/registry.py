"""Registry mapping ATS provider names to their adapter implementations."""

from __future__ import annotations

from hope_job_agent.sources.company_careers.providers.ashby import AshbyProvider
from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    ProviderError,
)
from hope_job_agent.sources.company_careers.providers.greenhouse import (
    GreenhouseProvider,
)
from hope_job_agent.sources.company_careers.providers.icims import ICIMSProvider
from hope_job_agent.sources.company_careers.providers.lever import LeverProvider
from hope_job_agent.sources.company_careers.providers.oraclecloud import (
    OracleCloudProvider,
)
from hope_job_agent.sources.company_careers.providers.smartrecruiters import (
    SmartRecruitersProvider,
)
from hope_job_agent.sources.company_careers.providers.workday import WorkdayProvider

_PROVIDER_REGISTRY: dict[str, BaseProvider] = {
    provider.name: provider
    for provider in (
        GreenhouseProvider(),
        LeverProvider(),
        AshbyProvider(),
        SmartRecruitersProvider(),
        WorkdayProvider(),
        OracleCloudProvider(),
        ICIMSProvider(),
    )
}


def get_provider(provider_name: str) -> BaseProvider:
    """Return the adapter for an ATS provider name."""

    key = provider_name.strip().casefold()
    try:
        return _PROVIDER_REGISTRY[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROVIDER_REGISTRY))
        raise ProviderError(
            f"No adapter registered for ATS provider '{provider_name}'. "
            f"Supported providers: {supported}."
        ) from exc


def registered_providers() -> list[str]:
    """Return the sorted list of registered provider names."""

    return sorted(_PROVIDER_REGISTRY)

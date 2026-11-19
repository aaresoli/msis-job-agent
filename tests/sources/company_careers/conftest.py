"""Shared test helpers for company_careers: a hermetic fake HTTP transport.

No test in this package ever touches a live career site. All HTTP flows through
``FakeTransport``, which returns registered in-memory responses keyed by a URL
substring so query-string variations do not matter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from hope_job_agent.sources.company_careers.http import HttpClient, HttpResponse

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Fixtures encode dates as "{DAYS_AGO:N}" (e.g. "{DAYS_AGO:3}") so postings stay
# within the adapter's rolling freshness window no matter when tests run.
_DAYS_AGO_PATTERN = re.compile(r"\{DAYS_AGO:(\d+)\}")


def _rebase_relative_dates(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        days_ago = int(match.group(1))
        target = datetime.now(UTC) - timedelta(days=days_ago)
        return target.strftime("%Y-%m-%d")

    return _DAYS_AGO_PATTERN.sub(_replace, text)


def load_fixture(name: str) -> Any:
    """Load a JSON fixture from the fixtures directory.

    Relative-date placeholders (``"{DAYS_AGO:N}"``) are resolved against the
    current date before parsing.
    """

    raw = (FIXTURES_DIR / name).read_text(encoding="utf-8")
    return json.loads(_rebase_relative_dates(raw))


class FakeTransport:
    """A deterministic transport that matches requests by URL substring."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, str, HttpResponse]] = []
        self.requests: list[dict[str, Any]] = []

    def route(
        self,
        *,
        method: str,
        contains: str,
        body: Any,
        status: int = 200,
        is_json: bool = True,
    ) -> FakeTransport:
        """Register a response for requests whose URL contains ``contains``."""

        text = json.dumps(body) if is_json else str(body)
        self._routes.append(
            (method.upper(), contains, HttpResponse(status, contains, text))
        )
        return self

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append({"method": method, "url": url, "headers": dict(headers)})
        for route_method, contains, response in self._routes:
            if route_method == method.upper() and contains in url:
                return HttpResponse(response.status_code, url, response.text)
        # Default: 404 so unrouted URLs surface clearly in tests.
        return HttpResponse(404, url, json.dumps({"error": "not found"}))


def make_client(transport: FakeTransport) -> HttpClient:
    """Build an HttpClient with no real delays for tests."""

    return HttpClient(
        transport=transport,
        min_interval_seconds=0.0,
        backoff_seconds=0.0,
        max_retries=1,
        sleep=lambda _seconds: None,
    )


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport: FakeTransport) -> HttpClient:
    return make_client(transport)

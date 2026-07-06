"""Polite, dependency-light HTTP client for public ATS job boards.

This module intentionally uses only the Python standard library so the source
runs and tests hermetically without adding ``httpx``/``requests`` to the runtime
dependency set. All network access flows through a small ``Transport`` protocol,
which tests replace with an in-memory fake so no test ever touches a live site.

Politeness features required by the project compliance rules:

* A clear, identifiable ``User-Agent``.
* A configurable per-host rate limit (minimum interval between requests).
* A request timeout.
* Bounded retries with exponential backoff for transient errors (429/5xx and
  network failures) only.
* Structured logging of every fetch attempt.

The client performs no login, cookie, CAPTCHA, or proxy-evasion behavior.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "KelleyHOPE-MSIS-JobAgent/0.1 "
    "(+https://kelley.iu.edu; compliant public career-page reader)"
)
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_MIN_INTERVAL_SECONDS = 1.0

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Statuses that indicate the source is blocking automated access. When we see
# these we should stop and disable the source rather than keep retrying.
BLOCKED_STATUS_CODES = frozenset({401, 403, 407, 451})


class HttpError(RuntimeError):
    """Raised when an HTTP request ultimately fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        blocked: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.blocked = blocked


@dataclass(frozen=True)
class HttpResponse:
    """A minimal HTTP response envelope."""

    status_code: int
    url: str
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        """Parse the response body as JSON."""

        return json.loads(self.text)


class Transport(Protocol):
    """Pluggable transport so tests can inject deterministic responses."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Perform one HTTP request and return the response."""


class UrllibTransport:
    """Default transport backed by ``urllib.request`` (standard library)."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = (
            urllib.request.Request(  # noqa: S310 - https/http only, validated below
                url,
                data=body,
                method=method,
                headers=dict(headers),
            )
        )
        scheme = urlsplit(url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise HttpError(f"Unsupported URL scheme for fetch: {scheme}")
        try:
            with urllib.request.urlopen(
                request, timeout=timeout
            ) as response:  # noqa: S310
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read()
                return HttpResponse(
                    status_code=int(getattr(response, "status", 200) or 200),
                    url=response.geturl(),
                    text=raw.decode(charset, errors="replace"),
                    headers={key: value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:  # noqa: PERF203 - explicit handling
            charset = "utf-8"
            try:
                body_text = exc.read().decode(charset, errors="replace")
            except Exception:  # pragma: no cover - defensive
                body_text = ""
            return HttpResponse(
                status_code=int(exc.code),
                url=url,
                text=body_text,
                headers={key: value for key, value in (exc.headers or {}).items()},
            )
        except urllib.error.URLError as exc:
            raise HttpError(f"Network error fetching {url}: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise HttpError(f"Network error fetching {url}: {exc}") from exc


class RateLimiter:
    """Enforce a minimum interval between requests to the same host."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: dict[str, float] = {}

    def wait(self, host: str) -> None:
        """Sleep just long enough to respect the per-host rate limit."""

        if self.min_interval_seconds <= 0:
            return
        now = self._monotonic()
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = now - last
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at[host] = now


class HttpClient:
    """A polite HTTP client for public ATS endpoints."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        rate_limiter: RateLimiter | None = None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport or UrllibTransport()
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self._sleep = sleep
        self.rate_limiter = rate_limiter or RateLimiter(
            min_interval_seconds=min_interval_seconds,
            sleep=sleep,
        )

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        accept: str = "application/json",
    ) -> HttpResponse:
        """Perform a GET request."""

        return self._request(method="GET", url=url, headers=headers, accept=accept)

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
        accept: str = "application/json",
    ) -> HttpResponse:
        """Perform a POST request with a JSON body."""

        body = json.dumps(payload).encode("utf-8")
        merged = {"Content-Type": "application/json", **(headers or {})}
        return self._request(
            method="POST",
            url=url,
            headers=merged,
            accept=accept,
            body=body,
        )

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET a URL and parse the response as JSON, raising on error status."""

        response = self.get(url, headers=headers)
        _raise_for_status(response)
        return response.json()

    def _request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        accept: str,
        body: bytes | None = None,
    ) -> HttpResponse:
        host = urlsplit(url).netloc
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
            **(headers or {}),
        }

        last_error: HttpError | None = None
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.wait(host)
            LOGGER.info(
                "company_careers fetch %s %s (attempt %s/%s)",
                method,
                url,
                attempt + 1,
                self.max_retries + 1,
            )
            try:
                response = self.transport.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    body=body,
                    timeout=self.timeout_seconds,
                )
            except HttpError as exc:
                last_error = exc
                LOGGER.warning("company_careers fetch error for %s: %s", url, exc)
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise

            if response.status_code in BLOCKED_STATUS_CODES:
                LOGGER.warning(
                    "company_careers fetch blocked (%s) for %s; disabling source",
                    response.status_code,
                    url,
                )
                raise HttpError(
                    f"Access blocked ({response.status_code}) for {url}",
                    status_code=response.status_code,
                    blocked=True,
                )

            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < self.max_retries
            ):
                LOGGER.warning(
                    "company_careers fetch retryable status %s for %s",
                    response.status_code,
                    url,
                )
                last_error = HttpError(
                    f"Retryable status {response.status_code} for {url}",
                    status_code=response.status_code,
                )
                self._backoff(attempt)
                continue

            return response

        assert last_error is not None  # noqa: S101 - loop always sets on failure
        raise last_error

    def _backoff(self, attempt: int) -> None:
        if self.backoff_seconds <= 0:
            return
        delay = self.backoff_seconds * (2**attempt)
        LOGGER.debug("company_careers backoff %.2fs before retry", delay)
        self._sleep(delay)


def _raise_for_status(response: HttpResponse) -> None:
    if response.status_code in BLOCKED_STATUS_CODES:
        raise HttpError(
            f"Access blocked ({response.status_code}) for {response.url}",
            status_code=response.status_code,
            blocked=True,
        )
    if response.status_code >= 400:
        raise HttpError(
            f"HTTP {response.status_code} for {response.url}",
            status_code=response.status_code,
        )

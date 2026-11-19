"""robots.txt policy checks for public career-page fetching.

We respect robots.txt where applicable. Because ATS *API* hosts (for example
``boards-api.greenhouse.io``) frequently do not serve a meaningful robots file
for their JSON endpoints, the policy is: fetch and parse robots.txt when we can;
if it explicitly disallows the target path for our User-Agent, refuse; if
robots.txt cannot be retrieved or parsed, default to allowing the request (fail
open) while still honoring rate limits. We never bypass an explicit disallow.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from hope_job_agent.sources.company_careers.http import HttpClient, HttpError

LOGGER = logging.getLogger(__name__)


class RobotsPolicy:
    """Cache and evaluate robots.txt rules per host for a given User-Agent."""

    def __init__(self, client: HttpClient, *, enabled: bool = True) -> None:
        self._client = client
        self.enabled = enabled
        self._parsers: dict[str, RobotFileParser | None] = {}

    def is_allowed(self, url: str) -> bool:
        """Return whether the configured User-Agent may fetch ``url``."""

        if not self.enabled:
            return True

        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        parser = self._parser_for(host, parts.scheme, parts.netloc)
        if parser is None:
            # robots.txt unavailable/unparseable -> fail open (still rate limited).
            return True
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        return parser.can_fetch(self._client.user_agent, path)

    def _parser_for(
        self,
        host: str,
        scheme: str,
        netloc: str,
    ) -> RobotFileParser | None:
        if host in self._parsers:
            return self._parsers[host]

        robots_url = urlunsplit((scheme, netloc, "/robots.txt", "", ""))
        parser: RobotFileParser | None = None
        try:
            response = self._client.get(robots_url, accept="text/plain")
            if response.status_code < 400 and response.text.strip():
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
            else:
                LOGGER.debug(
                    "No usable robots.txt for %s (status %s); allowing",
                    host,
                    response.status_code,
                )
        except HttpError as exc:
            LOGGER.debug("robots.txt fetch failed for %s: %s; allowing", host, exc)
            parser = None

        self._parsers[host] = parser
        return parser

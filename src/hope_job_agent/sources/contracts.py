"""Cursor-based contracts for future API and webhook-backed sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceBatch[T]:
    records: list[T]
    cursor: str | None = None
    watermark: datetime | None = None
    run_metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class ExternalSourceConnector[T](Protocol):
    source_name: str
    enabled: bool

    def fetch_page(
        self,
        *,
        cursor: str | None = None,
        watermark: datetime | None = None,
        limit: int = 100,
    ) -> SourceBatch[T]: ...


class SourceDisabledError(RuntimeError):
    pass

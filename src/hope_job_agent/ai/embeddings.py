"""Canonical EmbeddingGemma inputs shared by indexing and retrieval."""

from __future__ import annotations

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")
DOCUMENT_PREFIX = "title: {title} | text: "
QUERY_PREFIX = "task: search result | query: "


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def document_embedding_text(title: str | None, text: str) -> str:
    """Format a corpus item using EmbeddingGemma's retrieval prompt."""

    clean_title = _clean(title or "") or "none"
    return DOCUMENT_PREFIX.format(title=clean_title) + _clean(text)


def query_embedding_text(text: str) -> str:
    """Format a search query using EmbeddingGemma's retrieval prompt."""

    return QUERY_PREFIX + _clean(text)


def embedding_input_hash(text: str) -> str:
    """Hash the exact model input so prompt changes trigger re-indexing."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()

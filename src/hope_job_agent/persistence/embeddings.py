"""Embedding provider interface (stub implementations for future use)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Generate vector embeddings for job text."""

    model_name: str

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Return an embedding vector for ``text``."""
        ...


class LocalEmbeddingProvider(EmbeddingProvider):
    """Placeholder local embedding provider."""

    model_name = "local-stub"

    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Local embedding generation is not implemented in this migration."
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Placeholder OpenAI embedding provider."""

    model_name = "openai-stub"

    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError(
            "OpenAI embedding generation is not implemented in this migration."
        )

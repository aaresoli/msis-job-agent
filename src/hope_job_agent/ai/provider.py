"""Provider-neutral local model gateway with an Ollama implementation."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from hope_job_agent.platform.settings import get_platform_settings


@dataclass(frozen=True)
class ModelHealth:
    available: bool
    provider: str
    model: str | None
    detail: str | None = None


class ModelProvider(Protocol):
    name: str

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str: ...

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def health(self) -> ModelHealth: ...


class ModelUnavailable(RuntimeError):
    pass


class DisabledModelProvider:
    name = "disabled"

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        del messages, schema, temperature
        raise ModelUnavailable("Local model endpoint is not configured")

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        del messages
        raise ModelUnavailable("Local model endpoint is not configured")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        del texts
        raise ModelUnavailable("Local model endpoint is not configured")

    def health(self) -> ModelHealth:
        return ModelHealth(False, self.name, None, "Endpoint not configured")


class OllamaModelProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embedding_model: str = "embeddinggemma",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.timeout = httpx.Timeout(timeout_seconds, connect=5.0)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        if schema is not None:
            payload["format"] = schema
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            return str(response.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            raise ModelUnavailable(f"Ollama chat failed: {exc}") from exc

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        payload = {
            "model": self.chat_model,
            "messages": list(messages),
            "stream": True,
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    content = item.get("message", {}).get("content")
                    if content:
                        yield str(content)
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(f"Ollama streaming failed: {exc}") from exc

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.embedding_model, "input": list(texts)},
                timeout=self.timeout,
            )
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            return [[float(value) for value in vector] for vector in vectors]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ModelUnavailable(f"Ollama embedding failed: {exc}") from exc

    def health(self) -> ModelHealth:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ModelHealth(False, self.name, self.chat_model, str(exc))
        return ModelHealth(True, self.name, self.chat_model)


def get_model_provider() -> ModelProvider:
    settings = get_platform_settings()
    if not settings.ollama_base_url or not settings.ollama_chat_model:
        return DisabledModelProvider()
    return OllamaModelProvider(
        settings.ollama_base_url,
        settings.ollama_chat_model,
        settings.ollama_embedding_model,
    )

"""Provider-neutral local model gateway with an Ollama implementation."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx

from hope_job_agent.ai import telemetry
from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

# Which model a caller wants. The Celery queues split the same way
# (see workers/celery_app.py), so a task's queue and its model line up.
WORKLOAD_BATCH = "batch"
WORKLOAD_INTERACTIVE = "interactive"


@dataclass(frozen=True)
class ModelHealth:
    available: bool
    provider: str
    model: str | None
    detail: str | None = None
    embedding_model: str | None = None


class ModelProvider(Protocol):
    name: str
    # How many requests the backend decodes concurrently. Callers that fan out
    # size their pool from this instead of picking a number.
    max_parallel: int

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
    max_parallel = 1

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


def _installed_model_names(payload: Any) -> set[str]:
    """Extract every name Ollama reports from an ``/api/tags`` body.

    Ollama reports fully-qualified tags (``gpt-oss:120b``), but a config may
    reasonably omit the implicit ``:latest``. Both spellings are collected so
    the health check does not fail a working deployment on a naming detail.
    """

    names: set[str] = set()
    for model in (payload or {}).get("models", []):
        name = model.get("name") or model.get("model")
        if not name:
            continue
        names.add(str(name))
        base, _, tag = str(name).partition(":")
        if tag == "latest":
            names.add(base)
    return names


class OllamaModelProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embedding_model: str = "embeddinggemma",
        timeout_seconds: float = 300.0,
        num_ctx: int = 0,
        keep_alive: str = "",
        reasoning: str = "",
        workload: str = WORKLOAD_BATCH,
        max_parallel: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.reasoning = reasoning
        self.workload = workload
        # How many requests the *server* will decode at once. Callers that fan
        # out read this rather than guessing: exceeding it does not add
        # throughput, it just queues inside Ollama where nothing can see it.
        self.max_parallel = max(1, max_parallel)
        self.timeout = httpx.Timeout(timeout_seconds, connect=5.0)
        # One client per provider so calls reuse the connection. The previous
        # module-level httpx.post opened a fresh TCP connection per request,
        # which is paid once per job on a bulk enrichment run.
        self._client = httpx.Client(timeout=self.timeout)

    def _options(self, temperature: float) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": temperature}
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        return options

    def _payload(
        self, messages: Sequence[dict[str, str]], **extra: Any
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            **extra,
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        if self.reasoning:
            # gpt-oss reasons on every call whether or not anyone reads it, and
            # chat() returns message.content only -- so reasoning tokens are
            # pure decode cost on the extraction paths. This is the dial that
            # bounds them.
            payload["think"] = self.reasoning
        self._warn_if_over_context(messages)
        return payload

    def _warn_if_over_context(self, messages: Sequence[dict[str, str]]) -> None:
        """Log when a prompt is likely to be silently truncated.

        Ollama drops the overflow rather than erroring, and the graphs then
        report a validation or citation failure that looks like the model
        misbehaving. Surfacing it here keeps that debugging trail honest. The
        4-chars-per-token estimate is deliberately crude; it only needs to
        catch the order-of-magnitude case.
        """

        if not self.num_ctx:
            return
        characters = sum(len(message.get("content", "")) for message in messages)
        if characters // 4 > self.num_ctx:
            LOGGER.warning(
                "Prompt of ~%d characters likely exceeds num_ctx=%d for %s; "
                "Ollama will truncate it silently",
                characters,
                self.num_ctx,
                self.chat_model,
            )

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        payload = self._payload(
            messages, stream=False, options=self._options(temperature)
        )
        if schema is not None:
            payload["format"] = schema
        try:
            response = self._client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
            content = str(body["message"]["content"])
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            telemetry.record_failure(
                model=self.chat_model, workload=self.workload, operation="chat"
            )
            raise ModelUnavailable(f"Ollama chat failed: {exc}") from exc
        telemetry.record_call(
            body, model=self.chat_model, workload=self.workload, operation="chat"
        )
        return content

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        payload = self._payload(messages, stream=True, options=self._options(0.0))
        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    content = item.get("message", {}).get("content")
                    if content:
                        yield str(content)
                    # The terminal frame carries the same counters a
                    # non-streaming reply returns, so the coach path is
                    # measured on equal terms with the batch graphs.
                    if item.get("done"):
                        telemetry.record_call(
                            item,
                            model=self.chat_model,
                            workload=self.workload,
                            operation="stream_chat",
                        )
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            telemetry.record_failure(
                model=self.chat_model, workload=self.workload, operation="stream_chat"
            )
            raise ModelUnavailable(f"Ollama streaming failed: {exc}") from exc

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.embedding_model,
            "input": list(texts),
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        try:
            response = self._client.post(f"{self.base_url}/api/embed", json=payload)
            response.raise_for_status()
            body = response.json()
            vectors = body["embeddings"]
            result = [[float(value) for value in vector] for vector in vectors]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            telemetry.record_failure(
                model=self.embedding_model, workload=self.workload, operation="embed"
            )
            raise ModelUnavailable(f"Ollama embedding failed: {exc}") from exc
        telemetry.record_call(
            body,
            model=self.embedding_model,
            workload=self.workload,
            operation="embed",
        )
        return result

    def health(self) -> ModelHealth:
        """Report ready only if both configured models are actually installed.

        Checking that the server answers is not enough: a typo in
        ``OLLAMA_CHAT_MODEL`` leaves /health/ready reporting available while
        every real call fails, which is the failure this check exists to catch.
        """

        try:
            response = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
            installed = _installed_model_names(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            return ModelHealth(
                False, self.name, self.chat_model, str(exc), self.embedding_model
            )
        missing = [
            model
            for model in (self.chat_model, self.embedding_model)
            if model and model not in installed
        ]
        if missing:
            return ModelHealth(
                False,
                self.name,
                self.chat_model,
                f"model not pulled on the server: {', '.join(missing)}",
                self.embedding_model,
            )
        return ModelHealth(True, self.name, self.chat_model, None, self.embedding_model)


@lru_cache
def get_model_provider(workload: str = WORKLOAD_BATCH) -> ModelProvider:
    """Return the provider for ``workload``.

    ``interactive`` serves the streaming coach and prefers a smaller, faster
    model; everything else gets the batch model. Cached because the previous
    behaviour built a fresh provider — and so a fresh connection pool — on
    every call, including per-request paths.
    """

    settings = get_platform_settings()
    if not settings.ollama_base_url or not settings.ollama_chat_model:
        return DisabledModelProvider()
    chat_model = settings.ollama_chat_model
    num_ctx = settings.ollama_num_ctx
    reasoning = settings.ollama_batch_reasoning
    if workload == WORKLOAD_INTERACTIVE:
        if settings.ollama_interactive_model:
            chat_model = settings.ollama_interactive_model
        # A smaller window for the coach is not a downgrade: every parallel
        # slot's KV cache is sized from num_ctx, so the memory this gives back
        # is what lets the batch model hold more slots at once.
        num_ctx = settings.ollama_interactive_num_ctx or settings.ollama_num_ctx
        reasoning = settings.ollama_interactive_reasoning
    return OllamaModelProvider(
        settings.ollama_base_url,
        chat_model,
        settings.ollama_embedding_model,
        timeout_seconds=settings.ollama_timeout_seconds,
        num_ctx=num_ctx,
        keep_alive=settings.ollama_keep_alive,
        reasoning=reasoning,
        workload=workload,
        max_parallel=settings.ollama_num_parallel,
    )

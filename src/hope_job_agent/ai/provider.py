"""Provider-neutral local model gateway with a vLLM (OpenAI-compatible) implementation."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx

from hope_job_agent.ai import telemetry
from hope_job_agent.config.database import embedding_dimension
from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

# Which model a caller wants. The Celery queues split the same way
# (see workers/celery_app.py). On vLLM both workloads normally hit one
# continuously-batched server; the interactive override exists for a second
# served-model name if an operator ever splits them.
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


def _model_ids_from_openai_list(payload: Any) -> set[str]:
    """Collect every id an OpenAI-compatible ``/v1/models`` body reports."""

    ids: set[str] = set()
    for item in (payload or {}).get("data", []) or []:
        model_id = item.get("id") if isinstance(item, dict) else None
        if model_id:
            ids.add(str(model_id))
    return ids


class VllmModelProvider:
    """Talk to vLLM (chat) and an OpenAI-compatible embedding server.

    Chat and embeddings are separate processes on the Spark: a 120B MXFP4 MoE
    already claims most of the unified memory pool, so the 768-d embedding
    model runs on CPU and keeps the pgvector column width unchanged.
    """

    name = "vllm"

    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embedding_model: str = "google/embeddinggemma-300m",
        embedding_base_url: str = "",
        timeout_seconds: float = 300.0,
        max_model_len: int = 0,
        max_tokens: int = 2048,
        reasoning: str = "",
        workload: str = WORKLOAD_BATCH,
        max_parallel: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.embedding_base_url = (embedding_base_url or base_url).rstrip("/")
        self.max_model_len = max_model_len
        self.max_tokens = max_tokens
        self.reasoning = reasoning
        self.workload = workload
        self.max_parallel = max(1, max_parallel)
        self.timeout = httpx.Timeout(timeout_seconds, connect=5.0)
        self._client = httpx.Client(timeout=self.timeout)
        self._embedding_width: int | None = None

    def _warn_if_over_context(self, messages: Sequence[dict[str, str]]) -> None:
        """Log when a prompt is likely to hit the server's max_model_len.

        vLLM rejects over-long prompts rather than silently truncating, but the
        graphs still surface that as a validation failure. Surfacing it here
        keeps the debugging trail honest. The 4-chars-per-token estimate is
        deliberately crude; it only needs to catch order-of-magnitude cases.
        """

        if not self.max_model_len:
            return
        characters = sum(len(message.get("content", "")) for message in messages)
        if characters // 4 > self.max_model_len:
            LOGGER.warning(
                "Prompt of ~%d characters likely exceeds max_model_len=%d for %s",
                characters,
                self.max_model_len,
                self.chat_model,
            )

    def _chat_body(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float,
        stream: bool,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._warn_if_over_context(messages)
        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if schema is not None:
            # Guided JSON against the same Pydantic-exported schema the graphs
            # already validate. strict=True keeps the model inside the contract
            # instead of hoping the system prompt is enough.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "hope_payload",
                    "schema": schema,
                    "strict": True,
                },
            }
        if self.reasoning:
            # gpt-oss via vLLM's openai_gptoss reasoning parser. Empty leaves
            # the server default; "low"/"medium"/"high" bound CoT spend.
            body["reasoning_effort"] = self.reasoning
        return body

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        body = self._chat_body(
            messages, temperature=temperature, stream=False, schema=schema
        )
        try:
            response = self._client.post(
                f"{self.base_url}/v1/chat/completions", json=body
            )
            response.raise_for_status()
            payload = response.json()
            content = str(payload["choices"][0]["message"]["content"] or "")
        except (httpx.HTTPError, KeyError, TypeError, IndexError) as exc:
            telemetry.record_failure(
                model=self.chat_model, workload=self.workload, operation="chat"
            )
            raise ModelUnavailable(f"vLLM chat failed: {exc}") from exc
        telemetry.record_call(
            payload, model=self.chat_model, workload=self.workload, operation="chat"
        )
        return content

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        body = self._chat_body(messages, temperature=0.0, stream=True)
        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=body,
            ) as response:
                response.raise_for_status()
                usage: dict[str, Any] = {}
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[6:].strip()
                    else:
                        data = line.strip()
                    if not data or data == "[DONE]":
                        continue
                    item = json.loads(data)
                    if item.get("usage"):
                        usage = item["usage"]
                    choices = item.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield str(content)
                if usage:
                    telemetry.record_call(
                        {"usage": usage},
                        model=self.chat_model,
                        workload=self.workload,
                        operation="stream_chat",
                    )
                else:
                    telemetry.record_call(
                        {},
                        model=self.chat_model,
                        workload=self.workload,
                        operation="stream_chat",
                    )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
            telemetry.record_failure(
                model=self.chat_model, workload=self.workload, operation="stream_chat"
            )
            raise ModelUnavailable(f"vLLM streaming failed: {exc}") from exc

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        payload = {
            "model": self.embedding_model,
            "input": list(texts),
        }
        try:
            response = self._client.post(
                f"{self.embedding_base_url}/v1/embeddings", json=payload
            )
            response.raise_for_status()
            body = response.json()
            rows = sorted(body["data"], key=lambda row: int(row.get("index", 0)))
            result = [[float(value) for value in row["embedding"]] for row in rows]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            telemetry.record_failure(
                model=self.embedding_model, workload=self.workload, operation="embed"
            )
            raise ModelUnavailable(f"Embedding request failed: {exc}") from exc
        telemetry.record_call(
            body,
            model=self.embedding_model,
            workload=self.workload,
            operation="embed",
        )
        return result

    def health(self) -> ModelHealth:
        """Report ready only if chat and embedding endpoints serve the configured models."""

        try:
            chat_resp = self._client.get(f"{self.base_url}/v1/models", timeout=5.0)
            chat_resp.raise_for_status()
            chat_ids = _model_ids_from_openai_list(chat_resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            return ModelHealth(
                False, self.name, self.chat_model, str(exc), self.embedding_model
            )
        if self.chat_model not in chat_ids:
            return ModelHealth(
                False,
                self.name,
                self.chat_model,
                f"chat model not served: {self.chat_model} (have {sorted(chat_ids)})",
                self.embedding_model,
            )

        try:
            embed_resp = self._client.get(
                f"{self.embedding_base_url}/v1/models", timeout=5.0
            )
            embed_resp.raise_for_status()
            embed_ids = _model_ids_from_openai_list(embed_resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            return ModelHealth(
                False, self.name, self.chat_model, str(exc), self.embedding_model
            )
        if self.embedding_model not in embed_ids:
            return ModelHealth(
                False,
                self.name,
                self.chat_model,
                (
                    f"embedding model not served: {self.embedding_model} "
                    f"(have {sorted(embed_ids)})"
                ),
                self.embedding_model,
            )

        width_problem = self._embedding_width_detail()
        if width_problem:
            return ModelHealth(
                False, self.name, self.chat_model, width_problem, self.embedding_model
            )
        return ModelHealth(True, self.name, self.chat_model, None, self.embedding_model)

    def _embedding_width_detail(self) -> str | None:
        """Describe an embedding width that pgvector cannot store, if any.

        ``EMBEDDING_DIMENSION`` and ``VLLM_EMBEDDING_MODEL`` are set
        independently, so a plausible-looking pair can disagree. Today that
        only surfaces at write time, where ``_usable_vector`` discards the
        result and logs — leaving a deployment that reports ready and stores no
        embeddings at all. One probe embed moves the failure to the health
        check, where it is actually looked at. The width is cached because it
        is a property of the model, not of the request.
        """

        if self._embedding_width is None:
            try:
                vectors = self.embed(["dimension probe"])
            except ModelUnavailable as exc:
                return str(exc)
            if not vectors:
                return f"{self.embedding_model} returned no embedding vector"
            self._embedding_width = len(vectors[0])
        expected = embedding_dimension()
        if self._embedding_width != expected:
            return (
                f"{self.embedding_model} returns {self._embedding_width} dimensions "
                f"but EMBEDDING_DIMENSION is {expected}"
            )
        return None


# Back-compat alias for imports/tests mid-migration.
OllamaModelProvider = VllmModelProvider


@lru_cache
def get_model_provider(workload: str = WORKLOAD_BATCH) -> ModelProvider:
    """Return the provider for ``workload``.

    ``interactive`` serves the streaming coach. Cached because building a fresh
    provider — and so a fresh connection pool — on every call was paid once per
    request on the coach path.
    """

    settings = get_platform_settings()
    if not settings.vllm_base_url or not settings.vllm_chat_model:
        return DisabledModelProvider()
    chat_model = settings.vllm_chat_model
    max_tokens = settings.vllm_max_tokens
    reasoning = settings.vllm_batch_reasoning
    if workload == WORKLOAD_INTERACTIVE:
        if settings.vllm_interactive_model:
            chat_model = settings.vllm_interactive_model
        max_tokens = settings.vllm_interactive_max_tokens or settings.vllm_max_tokens
        reasoning = settings.vllm_interactive_reasoning
    return VllmModelProvider(
        settings.vllm_base_url,
        chat_model,
        settings.vllm_embedding_model,
        embedding_base_url=settings.vllm_embedding_base_url,
        timeout_seconds=settings.vllm_timeout_seconds,
        max_model_len=settings.vllm_max_model_len,
        max_tokens=max_tokens,
        reasoning=reasoning,
        workload=workload,
        max_parallel=settings.vllm_max_num_seqs,
    )

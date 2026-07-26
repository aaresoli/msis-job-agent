"""OpenAI-compatible embedding sidecar for the Spark.

vLLM serving ``openai/gpt-oss-120b`` already claims most of the 128GB unified
memory pool. The platform still needs 768-d ``embeddinggemma`` vectors for
pgvector, so embeddings run here on CPU and speak the same
``/v1/embeddings`` contract the chat provider uses.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("VLLM_EMBEDDING_MODEL", "google/embeddinggemma-300m")
HOST = os.environ.get("EMBED_HOST", "0.0.0.0")
PORT = int(os.environ.get("EMBED_PORT", "8002"))

app = FastAPI(title="HOPE embedding sidecar", version="1.0.0")
_model: Any = None


def _load_model() -> Any:
    global _model
    if _model is None:
        # Imported lazily so `import hope_job_agent.ai.embed_server` in tests
        # does not pull torch/sentence-transformers into the API image's cold
        # path. The sidecar image installs them explicitly.
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_ID, device="cpu")
    return _model


class EmbeddingRequest(BaseModel):
    model: str = MODEL_ID
    input: str | list[str]


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: dict[str, int] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    _load_model()
    return {"status": "ok", "model": MODEL_ID}


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "hope"}],
    }


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def create_embeddings(body: EmbeddingRequest) -> EmbeddingResponse:
    if body.model and body.model != MODEL_ID:
        raise HTTPException(
            status_code=404,
            detail=f"model {body.model!r} is not served; have {MODEL_ID!r}",
        )
    texts = [body.input] if isinstance(body.input, str) else list(body.input)
    if not texts:
        raise HTTPException(status_code=400, detail="input must not be empty")
    vectors = _load_model().encode(texts, normalize_embeddings=True)
    data = [
        EmbeddingData(index=index, embedding=[float(v) for v in row])
        for index, row in enumerate(vectors)
    ]
    return EmbeddingResponse(
        data=data,
        model=MODEL_ID,
        usage={"prompt_tokens": 0, "total_tokens": 0},
    )


def main() -> None:
    import uvicorn

    # Load before binding so a missing model fails the container, not the
    # first student request that needed an embedding.
    _load_model()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()

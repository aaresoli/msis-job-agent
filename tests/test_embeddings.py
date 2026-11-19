"""Embedding prompt and stale-index contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from hope_job_agent.ai.embeddings import (
    document_embedding_text,
    embedding_input_hash,
    query_embedding_text,
)
from hope_job_agent.ops.reconcile import find_reconciliation_backlog


def test_embeddinggemma_uses_distinct_canonical_prompts() -> None:
    document = document_embedding_text(" Data  Analyst ", "Build\n SQL dashboards")
    query = query_embedding_text(" Find   analytics roles ")

    assert document == "title: Data Analyst | text: Build SQL dashboards"
    assert query == "task: search result | query: Find analytics roles"
    assert embedding_input_hash(document) == embedding_input_hash(document)
    assert embedding_input_hash(document) != embedding_input_hash(query)


def test_reconcile_finds_wrong_model_and_wrong_input_hash() -> None:
    current_id, wrong_model_id, stale_hash_id = uuid4(), uuid4(), uuid4()
    jobs = [
        SimpleNamespace(id=current_id, title="Analyst", description="Build reports"),
        SimpleNamespace(id=wrong_model_id, title="Engineer", description="Build APIs"),
        SimpleNamespace(
            id=stale_hash_id, title="Scientist", description="Build models"
        ),
    ]
    current_input = document_embedding_text("Analyst", "Build reports")
    rows = [
        (
            jobs[0],
            SimpleNamespace(
                embedding_model="google/embeddinggemma-300m",
                embedding_input_hash=embedding_input_hash(current_input),
            ),
        ),
        (
            jobs[1],
            SimpleNamespace(
                embedding_model="old/model",
                embedding_input_hash=embedding_input_hash(
                    document_embedding_text("Engineer", "Build APIs")
                ),
            ),
        ),
        (
            jobs[2],
            SimpleNamespace(
                embedding_model="google/embeddinggemma-300m",
                embedding_input_hash="stale",
            ),
        ),
    ]

    class _Scalars:
        def __init__(self, values):  # noqa: ANN001
            self.values = values

        def all(self):  # noqa: ANN201
            return self.values

    class _Rows:
        @staticmethod
        def all():  # noqa: ANN205
            return rows

    class _Session:
        scalar_calls = 0

        def scalars(self, _statement):  # noqa: ANN001, ANN201
            self.scalar_calls += 1
            return _Scalars([])

        @staticmethod
        def execute(_statement):  # noqa: ANN001, ANN205
            return _Rows()

    backlog = find_reconciliation_backlog(
        _Session(),
        embedding_model="google/embeddinggemma-300m",  # type: ignore[arg-type]
    )

    assert backlog["unembedded"] == [str(wrong_model_id), str(stale_hash_id)]

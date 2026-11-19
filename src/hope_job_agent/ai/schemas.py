"""Validated shapes for local-model output.

Every graph in :mod:`hope_job_agent.ai.graphs` sends one of these models'
JSON Schema to the provider as its ``format``, then validates the reply against
the same model. Deriving both from one definition means the contract we ask for
and the contract we enforce cannot drift apart.

Validation failure is never fatal: callers route the item to ``review`` so a
human sees it, which is the same degradation path a model outage takes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceItem(BaseModel):
    """One claim, tied to the text that supports it.

    ``quote`` is required on purpose. The project's compliance rule is that
    sponsorship, salary, and location claims must be traceable to posting text
    rather than inferred, so an evidence item with no quote is not evidence.
    Extra keys are allowed so the model can add context without failing.
    """

    model_config = ConfigDict(extra="allow")

    quote: str = Field(min_length=1)

    @field_validator("quote")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence quote must not be blank")
        return value


class JobEnrichmentPayload(BaseModel):
    """Structured extraction for one job posting."""

    model_config = ConfigDict(extra="ignore")

    skills: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    work_auth_evidence: list[EvidenceItem] = Field(default_factory=list)
    salary_evidence: list[EvidenceItem] = Field(default_factory=list)
    location_evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("skills", "requirements", mode="after")
    @classmethod
    def _drop_blanks(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class MatchScorePayload(BaseModel):
    """A single fit judgement from the reranking model.

    ``reason`` is required. Without it the model returns a bare number that
    nothing can audit and no student can act on, and the explanation shown on a
    match card falls back to restating the deterministic rubric -- which is not
    an explanation of the model's opinion, it is the input to it.
    """

    model_config = ConfigDict(extra="ignore")

    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("reason")
    @classmethod
    def _reject_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value.strip()


class ResumeProfilePayload(BaseModel):
    """A profile proposed from a resume, for a human to confirm.

    ``evidence`` carries quotes rather than bare strings so the same
    verbatim check the enrichment path uses can run here: a resume-derived
    profile is shown to the student as what the system believes about them,
    and an invented skill is harder to notice than an invented job attribute.

    Nothing here is authoritative. ``parse_status`` stays ``review`` even on a
    clean parse, so this is a draft the student edits, never a profile the
    platform asserts.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=256)
    # Required, and non-empty, on purpose. Given a default these become optional
    # in the generated JSON Schema, and a structured-output model will happily
    # omit them -- which validated cleanly as a "ready" profile containing
    # nothing at all. A resume with no extractable skill is a review case.
    skills: list[str] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    # Genuinely optional: most resumes never state a target role, and requiring
    # one would push the model to infer exactly what it is told not to.
    target_roles: list[str] = Field(default_factory=list)

    @field_validator("skills", "target_roles", mode="after")
    @classmethod
    def _drop_blanks(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @field_validator("skills", mode="after")
    @classmethod
    def _require_a_surviving_skill(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one non-blank skill is required")
        return value


class MarketSignalPayload(BaseModel):
    """One time-bounded hiring signal, with the posts that support it."""

    model_config = ConfigDict(extra="ignore")

    topic: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=10_000)
    company_name: str | None = Field(default=None, max_length=512)
    role_tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Non-empty because an uncited signal is exactly what this pipeline exists
    # to reject. The graph additionally checks each URL against the posts it
    # supplied, so the model cannot cite a source it was never shown.
    citations: list[str] = Field(min_length=1)


class MarketSignalsPayload(BaseModel):
    """The full reply from the market-pulse extraction step."""

    model_config = ConfigDict(extra="ignore")

    signals: list[MarketSignalPayload] = Field(default_factory=list)


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the provider-facing JSON Schema for ``model``.

    Ollama's structured-output mode wants a self-contained schema, so ``$defs``
    references are inlined rather than left as ``$ref`` pointers.
    """

    return model.model_json_schema(ref_template="#/$defs/{model}")

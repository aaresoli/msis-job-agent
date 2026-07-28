"""Idempotent background tasks for AI enrichment, matching, and retention."""

from __future__ import annotations

import io
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from celery import Task
from celery.signals import worker_process_init
from docx import Document
from langgraph.graph.state import CompiledStateGraph
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from hope_job_agent.ai import graphs
from hope_job_agent.ai.checkpoints import (
    delete_checkpoint_thread,
    postgres_checkpointer,
)
from hope_job_agent.ai.embeddings import (
    document_embedding_text,
    embedding_input_hash,
    query_embedding_text,
)
from hope_job_agent.ai.graphs import (
    build_job_enrichment_graph,
    build_market_pulse_graph,
    build_match_generation_graph,
    build_resume_parse_graph,
)
from hope_job_agent.ai.provider import ModelUnavailable, get_model_provider
from hope_job_agent.ai.ranking import normalize_rule_score
from hope_job_agent.config.database import embedding_dimension
from hope_job_agent.db.models import (
    JobMatchRecord,
    JobPostingRecord,
    StudentProfileRecord,
)
from hope_job_agent.db.platform_models import (
    CoachThread,
    ConsentRecord,
    DeletionRequest,
    JobEnrichment,
    MarketPost,
    MarketSignal,
    ResumeDocument,
    SourceQuarantineRecord,
    User,
)
from hope_job_agent.db.session import (
    create_db_engine,
    create_session_factory,
    session_scope,
)
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.ops.locks import AlreadyRunning, single_flight
from hope_job_agent.persistence.embedding_repository import EmbeddingRepository
from hope_job_agent.persistence.mapping import job_from_record
from hope_job_agent.persistence.source_run_repository import SourceRunRepository
from hope_job_agent.pipeline.run_mvp import MvpPipelineError, run_mvp_pipeline
from hope_job_agent.pipeline.run_posts import ingest_market_posts
from hope_job_agent.platform.documents import (
    delete_private_document,
    get_private_document,
)
from hope_job_agent.platform.settings import get_platform_settings
from hope_job_agent.scoring.ranker import rank_jobs_for_student
from hope_job_agent.sources.apify_linkedin_posts import (
    SOURCE_NAME as POSTS_SOURCE_NAME,
)
from hope_job_agent.sources.registry import (
    SourceComplianceError,
    ensure_source_allowed,
)
from hope_job_agent.workers.celery_app import celery_app

LOGGER = logging.getLogger(__name__)

# Sources the scheduler is allowed to refresh unattended. Everything else in
# the registry is either a local-file export (needs an operator-supplied path)
# or not approved for automated collection.
REFRESHABLE_SOURCES = frozenset({"company_careers", "apify_linkedin"})

# ``source_name`` of the parent run recorded by :func:`refresh_all`. Each source
# in the sweep still writes its own child run, so source-health views can filter
# this aggregate out.
ORCHESTRATOR_SOURCE = "refresh_all"

# Above the task's own 3-hour hard limit, so the lock is released by the run
# that took it or by the worker dying, never by expiry mid-sweep.
REFRESH_ALL_LOCK_TTL_SECONDS = 12600

# Must exceed hope.market.refresh's own time limit so the TTL only releases the
# lock for a worker that actually died, not one still working.
MARKET_PULSE_LOCK_TTL_SECONDS = 900

# A local model server restarts, reloads, or briefly saturates often enough that
# a first failure is usually transient. Without a retry these tasks wait for the
# nightly reconcile, so a model reload at 09:00 means no embeddings until 02:00.
# ``ModelUnavailable`` is a ``RuntimeError``, so this covers both it and the
# graph failures that surface the same way. Backoff is capped well under each
# task's soft time limit so a retrying task cannot be killed mid-sleep.
#
# Deliberately not applied to the source refreshes: they set acks_late=False and
# max_retries=0 because retrying a half-finished crawl re-hits rate-limited
# employer boards.
LLM_RETRY_EXCEPTIONS = (RuntimeError,)
LLM_RETRY_BACKOFF_MAX_SECONDS = 60


@lru_cache
def session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory.

    Cached because every call to :func:`create_db_engine` builds a *new*
    connection pool. Celery forks one process per worker child, so an uncached
    factory leaked a pool per task invocation.
    """

    return create_session_factory(create_db_engine(storage="postgres"))


@worker_process_init.connect
def _reset_factory_after_fork(**_kwargs: object) -> None:
    """Drop any inherited engine or model client so forked children never share.

    Sockets survive ``fork``; two processes writing to one connection corrupts
    the protocol. Clearing the caches makes each child build its own. The model
    provider is cached for the same reason the session factory is — it holds a
    pooled HTTP client — so it has the same fork hazard and the same fix.
    """

    session_factory.cache_clear()
    get_model_provider.cache_clear()


def _usable_vector(vector: list[float], label: str) -> bool:
    """Return whether ``vector`` matches the configured pgvector width.

    A mismatch means the configured embedding model does not agree with
    ``EMBEDDING_DIMENSION``, and the column cannot store the result. That used
    to be swallowed by a bare length check, producing a system with no
    embeddings and no error anywhere. It is a misconfiguration, so it is
    logged.
    """

    expected = embedding_dimension()
    if len(vector) == expected:
        return True
    LOGGER.warning(
        "%s embedding has %d dimensions but EMBEDDING_DIMENSION is %d; "
        "check EMBEDDING_MODEL. Vector discarded.",
        label,
        len(vector),
        expected,
    )
    return False


@celery_app.task(
    name="hope.enrichment.job",
    autoretry_for=LLM_RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_jitter=True,
    retry_backoff_max=LLM_RETRY_BACKOFF_MAX_SECONDS,
    max_retries=3,
)
def enrich_job(job_id: str) -> dict[str, Any]:
    with session_scope(session_factory()) as db:
        job = db.get(JobPostingRecord, UUID(job_id))
        if job is None:
            return {"status": "missing", "job_id": job_id}
        existing = db.scalar(
            select(JobEnrichment).where(
                JobEnrichment.job_id == job.id,
                JobEnrichment.version == "enrichment-v1",
            )
        )
        if existing is not None and existing.status == "ready":
            return {"status": "unchanged", "job_id": job_id}
        provider = get_model_provider()
        with postgres_checkpointer() as checkpointer:
            graph = build_job_enrichment_graph(provider, checkpointer)
            result = graph.invoke(
                {
                    "job_id": job_id,
                    "title": job.title,
                    "description": job.description or "",
                },
                config={"configurable": {"thread_id": f"enrichment:{job_id}"}},
            )
        payload = result.get("enrichment", {})
        row = existing or JobEnrichment(
            job_id=job.id,
            version="enrichment-v1",
            # Read from settings rather than provider.health(), which costs a
            # GET /api/tags on every newly enriched job to learn a value the
            # configuration already holds.
            model=get_platform_settings().vllm_chat_model,
        )
        row.skills = payload.get("skills", [])
        row.requirements = payload.get("requirements", [])
        row.work_auth_evidence = payload.get("work_auth_evidence", [])
        row.confidence = payload.get("confidence")
        row.status = result.get("status", "review")
        row.payload = payload
        if existing is None:
            db.add(row)
        return {"status": row.status, "job_id": job_id}


# Embedding is a separate task from enrichment on purpose. It used to run
# inside enrich_job, which coupled two unrelated failure modes: a posting whose
# enrichment was routed to review still needs a vector, because similarity
# search is what surfaces it at all. It also meant one HTTP round trip per job
# for a model that accepts a whole list at once.
EMBEDDING_BATCH_SIZE = 32


@celery_app.task(
    name="hope.enrichment.embed",
    autoretry_for=LLM_RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_jitter=True,
    retry_backoff_max=LLM_RETRY_BACKOFF_MAX_SECONDS,
    max_retries=3,
)
def embed_jobs(job_ids: list[str]) -> dict[str, Any]:
    """Embed a batch of postings in as few provider calls as possible.

    Skips any posting whose stored ``embedding_input_hash`` already matches the
    text we would send, so re-running over a corpus costs nothing for the parts
    that have not changed.
    """

    settings = get_platform_settings()
    provider = get_model_provider()
    identifiers = [UUID(raw_id) for raw_id in job_ids]
    with session_scope(session_factory()) as db:
        repository = EmbeddingRepository(db)
        # Two queries for the whole batch rather than two per posting. A task
        # whose reason for existing is batching should not open with an N+1.
        jobs = db.scalars(
            select(JobPostingRecord).where(JobPostingRecord.id.in_(identifiers))
        ).all()
        stored = repository.get_embeddings(identifiers)

        pending: list[tuple[UUID, str, str]] = []
        for job in jobs:
            model_input = document_embedding_text(job.title, job.description or "")
            digest = embedding_input_hash(model_input)
            existing = stored.get(job.id)
            if (
                existing is not None
                and existing.embedding_input_hash == digest
                and existing.embedding_model == settings.embedding_model
            ):
                continue
            pending.append((job.id, model_input, digest))

        if not pending:
            return {"status": "unchanged", "embedded": 0, "requested": len(job_ids)}

        embedded = 0
        for start in range(0, len(pending), EMBEDDING_BATCH_SIZE):
            chunk = pending[start : start + EMBEDDING_BATCH_SIZE]
            try:
                vectors = provider.embed([text for _, text, _ in chunk])
            except ModelUnavailable:
                LOGGER.warning("Embedding batch skipped: local model unavailable")
                break
            if len(vectors) != len(chunk):
                LOGGER.warning(
                    "Embedding response returned %d vectors for %d inputs; "
                    "batch discarded",
                    len(vectors),
                    len(chunk),
                )
                continue
            for (job_id, _, digest), vector in zip(chunk, vectors, strict=True):
                if not _usable_vector(vector, "job"):
                    continue
                repository.upsert_embedding(
                    job_id, vector, settings.embedding_model, digest
                )
                embedded += 1
        return {
            "status": "ready" if embedded else "review",
            "embedded": embedded,
            "requested": len(job_ids),
        }


@celery_app.task(
    bind=True,
    name="hope.sources.refresh",
    acks_late=False,
    max_retries=0,
    time_limit=5400,
    soft_time_limit=5100,
)
def refresh_source(
    self: Task,  # Celery binds the task instance via bind=True
    source_name: str,
    limit: int | None = None,
    max_companies: int | None = None,
    dry_run: bool = False,
    full_refresh: bool = False,
) -> dict[str, Any]:
    """Run the ingestion pipeline for one approved source into Postgres.

    Retries are disabled: a crawl is expensive and partially-applied work is
    already persisted, so a failed run is recorded as a failed ``SourceRun``
    (which drives the source-health alert) and left for the next schedule.
    """

    if source_name not in REFRESHABLE_SOURCES:
        return {
            "source": source_name,
            "status": "rejected",
            "reason": (
                f"'{source_name}' is not refreshable on a schedule. "
                f"Allowed: {', '.join(sorted(REFRESHABLE_SOURCES))}."
            ),
        }
    try:
        ensure_source_allowed(source_name)
    except SourceComplianceError as exc:
        return {"source": source_name, "status": "disabled", "reason": str(exc)}

    with tempfile.TemporaryDirectory(prefix=f"hope-refresh-{source_name}-") as tmpdir:
        try:
            result = run_mvp_pipeline(
                source_name=source_name,
                profiles_path=None,
                output_path=Path(tmpdir) / "jobs.json",
                limit=limit,
                max_companies=max_companies,
                dry_run=dry_run,
                full_refresh=full_refresh,
                storage="postgres",
            )
        except MvpPipelineError as exc:
            _record_failed_source_run(source_name, str(exc))
            raise

    summary = result.summary
    return {
        "source": source_name,
        "status": "completed",
        "task_id": self.request.id,
        "run_id": summary["run_id"],
        "raw_count": summary["raw_count"],
        "unique_count": summary["unique_count"],
        "duplicate_count": summary.get("duplicate_count", 0),
        "warnings": len(summary["warnings"]),
    }


def _record_failed_source_run(source_name: str, error: str) -> None:
    """Persist a failed SourceRun so source-health alerts can see the failure."""

    try:
        with session_scope(session_factory()) as db:
            runs = SourceRunRepository(db)
            run = runs.start_run(source_name, metadata={"trigger": "scheduled"})
            runs.fail_run(run.id, error[:4096])
    except Exception:  # noqa: BLE001 - never mask the original pipeline failure
        LOGGER.exception("Could not record failed source run for %s", source_name)


@celery_app.task(
    name="hope.enrichment.resume",
    autoretry_for=LLM_RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_jitter=True,
    retry_backoff_max=LLM_RETRY_BACKOFF_MAX_SECONDS,
    max_retries=3,
)
def parse_resume(resume_id: str) -> dict[str, Any]:
    with session_scope(session_factory()) as db:
        resume = db.get(ResumeDocument, UUID(resume_id))
        if resume is None:
            return {"status": "missing", "resume_id": resume_id}
        content = get_private_document(resume.object_key)
        if resume.media_type == "application/pdf":
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            document = Document(io.BytesIO(content))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        if not text.strip():
            resume.parse_status = "review"
            resume.parsed_profile = {"warning": "No selectable resume text found"}
            return {"status": "review", "resume_id": resume_id}
        graph = build_resume_parse_graph(get_model_provider())
        result = graph.invoke({"resume_text": text[:30000]})
        if result.get("status") == graphs.STATUS_UNAVAILABLE:
            resume.parse_status = "awaiting_local_ai"
            resume.parsed_profile = {"warning": result.get("error", "")}
        elif result.get("status") == graphs.STATUS_READY:
            # Still ``review``: a clean parse is a draft the student confirms,
            # never a profile the platform asserts about them.
            resume.parse_status = "review"
            resume.parsed_profile = result["profile"]
        else:
            resume.parse_status = "review"
            resume.parsed_profile = {"warning": result.get("error", "")}
        return {"status": resume.parse_status, "resume_id": resume_id}


@celery_app.task(name="hope.sources.refresh_posts")
def refresh_posts(
    dataset_id: str | None = None,
    run_id: str | None = None,
    trigger_run: bool = False,
    max_items: int | None = None,
    enqueue_pulse: bool = True,
) -> dict[str, Any]:
    """Fetch LinkedIn hiring posts from Apify and refresh market signals.

    Runs on the ``ingest`` queue. Ingests MSIS-relevant posts into
    ``market_posts`` then enqueues :func:`refresh_market_pulse` so the LLM
    signal extraction picks up the new posts. :func:`refresh_all` passes
    ``enqueue_pulse=False`` because it runs the pulse itself once every source
    has landed.
    """

    with session_scope(session_factory()) as db:
        outcome = ingest_market_posts(
            db,
            dataset_id=dataset_id,
            run_id=run_id,
            trigger_run=trigger_run,
            max_items=max_items,
        )
    if enqueue_pulse and (outcome["inserted"] or outcome["updated"]):
        refresh_market_pulse.apply_async(countdown=2)
    return {"status": "completed", **outcome}


@celery_app.task(
    bind=True,
    name="hope.sources.refresh_all",
    acks_late=False,
    max_retries=0,
    time_limit=10800,
    soft_time_limit=10500,
)
def refresh_all(
    self: Task,  # Celery binds the task instance via bind=True
    sources: list[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    full_refresh: bool = False,
    include_posts: bool = True,
    posts_dataset_id: str | None = None,
    posts_run_id: str | None = None,
    posts_trigger_run: bool = False,
    posts_max_items: int | None = None,
    refresh_signals: bool = True,
) -> dict[str, Any]:
    """Refresh every scheduled source in one sweep and record a parent run.

    Jobs (``job_postings``) and posts (``market_posts``) keep their separate
    tables, dedup rules, and lifecycles; this task only sequences them:

    1. each approved job source runs through :func:`refresh_source`,
    2. LinkedIn posts run through :func:`refresh_posts`,
    3. every source upserts into Postgres independently — one failure is
       recorded and the sweep continues,
    4. a single ``refresh_all`` :class:`SourceRun` aggregates the per-source
       results (each source also keeps its own child run), and
    5. market signals are re-extracted once, after all posts have landed.

    Dashboard snapshots are TTL-cached inside the web process, so they pick the
    new rows up on their own — there is no cache for the worker to invalidate.

    Held under a single-flight lock. The scheduler fires every four hours and
    the operator-facing ``/internal/v1`` route stays available, so without it a
    manual trigger can land on top of a running sweep and double the request
    rate against employer boards — the exact thing the adapters rate-limit for.
    """

    try:
        with single_flight("refresh-all", REFRESH_ALL_LOCK_TTL_SECONDS):
            return _refresh_all_locked(
                self,
                sources=sources,
                limit=limit,
                dry_run=dry_run,
                full_refresh=full_refresh,
                include_posts=include_posts,
                posts_dataset_id=posts_dataset_id,
                posts_run_id=posts_run_id,
                posts_trigger_run=posts_trigger_run,
                posts_max_items=posts_max_items,
                refresh_signals=refresh_signals,
            )
    except AlreadyRunning:
        LOGGER.warning("Source sweep already running; skipping this window")
        return {"status": "skipped", "reason": "already running"}


def _refresh_all_locked(
    self: Task,
    *,
    sources: list[str] | None,
    limit: int | None,
    dry_run: bool,
    full_refresh: bool,
    include_posts: bool,
    posts_dataset_id: str | None,
    posts_run_id: str | None,
    posts_trigger_run: bool,
    posts_max_items: int | None,
    refresh_signals: bool,
) -> dict[str, Any]:
    selected = list(sources) if sources is not None else sorted(REFRESHABLE_SOURCES)
    started = datetime.now(UTC)
    parent_run_id = _start_orchestrator_run(
        {
            "trigger": "refresh_all",
            "task_id": self.request.id,
            "sources": selected,
            "include_posts": include_posts,
        }
    )

    results = [
        _refresh_job_source(
            source_name,
            limit=limit,
            dry_run=dry_run,
            full_refresh=full_refresh,
        )
        for source_name in selected
    ]
    if include_posts:
        results.append(
            _refresh_posts_source(
                dataset_id=posts_dataset_id,
                run_id=posts_run_id,
                trigger_run=posts_trigger_run,
                max_items=posts_max_items,
            )
        )

    signals: dict[str, Any] | None = None
    if refresh_signals and any(
        result.get("inserted") or result.get("updated")
        for result in results
        if result["kind"] == "posts"
    ):
        signals = _refresh_signals()

    errors = [
        f"{result['source']}: {result['error']}"
        for result in results
        if result["status"] == "failed"
    ]
    all_failed = bool(errors) and not any(
        result["status"] == "completed" for result in results
    )
    summary = {
        "trigger": "refresh_all",
        "sources": results,
        "signals": signals,
        "raw_count": sum(int(result.get("raw_count") or 0) for result in results),
        "duplicate_count": sum(
            int(result.get("duplicate_count") or 0) for result in results
        ),
        "errors": errors,
        "runtime_seconds": round(
            (datetime.now(UTC) - started).total_seconds(),
            3,
        ),
    }
    _finish_orchestrator_run(parent_run_id, summary, failed=all_failed)

    if all_failed:
        status = "failed"
    elif errors:
        status = "partial_success"
    else:
        status = "completed"
    return {
        "status": status,
        "task_id": self.request.id,
        "run_id": None if parent_run_id is None else str(parent_run_id),
        "sources": results,
        "signals": signals,
        "errors": errors,
    }


def _refresh_job_source(source_name: str, **options: Any) -> dict[str, Any]:
    """Run one job source, converting a crash into a recorded per-source failure."""

    try:
        return {"kind": "jobs", **refresh_source.run(source_name, **options)}
    except Exception as exc:  # noqa: BLE001 - one bad source must not stop the sweep
        LOGGER.exception("refresh_all: source %s failed", source_name)
        return {
            "source": source_name,
            "kind": "jobs",
            "status": "failed",
            "error": str(exc)[:4096],
        }


def _refresh_posts_source(**options: Any) -> dict[str, Any]:
    """Run the LinkedIn posts ingest, deferring signal extraction to the sweep."""

    try:
        outcome = refresh_posts.run(enqueue_pulse=False, **options)
        return {
            "kind": "posts",
            # Posts count their fetch under "fetch"; lift it so the parent run
            # can aggregate raw_count the same way across jobs and posts.
            "raw_count": (outcome.get("fetch") or {}).get("raw_count", 0),
            **outcome,
        }
    except Exception as exc:  # noqa: BLE001 - see _refresh_job_source
        LOGGER.exception("refresh_all: posts ingest failed")
        return {
            "source": POSTS_SOURCE_NAME,
            "kind": "posts",
            "status": "failed",
            "error": str(exc)[:4096],
        }


def _refresh_signals() -> dict[str, Any]:
    """Re-extract market signals; a local-model outage degrades, not fails."""

    try:
        return dict(refresh_market_pulse.run())
    except Exception as exc:  # noqa: BLE001 - signals are best-effort
        LOGGER.exception("refresh_all: market pulse failed")
        return {"status": "failed", "error": str(exc)[:4096]}


def _start_orchestrator_run(metadata: dict[str, Any]) -> UUID | None:
    try:
        with session_scope(session_factory()) as db:
            run = SourceRunRepository(db).start_run(
                ORCHESTRATOR_SOURCE, metadata=metadata
            )
            return run.id
    except Exception:  # noqa: BLE001 - the sweep is still worth running
        LOGGER.exception("refresh_all: could not open the parent source run")
        return None


def _finish_orchestrator_run(
    run_id: UUID | None,
    summary: dict[str, Any],
    *,
    failed: bool,
) -> None:
    if run_id is None:
        return
    try:
        with session_scope(session_factory()) as db:
            runs = SourceRunRepository(db)
            # finish_run stores the per-source summary and marks the run
            # partial_success when any source errored; a sweep where nothing
            # succeeded is downgraded to failed for source-health alerting.
            runs.finish_run(run_id, summary=summary)
            if failed:
                runs.fail_run(run_id, "; ".join(summary["errors"])[:4096])
    except Exception:  # noqa: BLE001 - never mask per-source outcomes
        LOGGER.exception("refresh_all: could not close the parent source run")


@celery_app.task(
    name="hope.market.refresh",
    autoretry_for=LLM_RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_jitter=True,
    retry_backoff_max=LLM_RETRY_BACKOFF_MAX_SECONDS,
    max_retries=3,
)
def refresh_market_pulse() -> dict[str, Any]:
    """Re-extract market signals from the most recent posts.

    Held under a single-flight lock. This is the one signal-writing path with
    no natural dedup key: ``acks_late`` means a worker killed mid-run has its
    message redelivered, and a second pass over the same posts inserts a second
    set of ``MarketSignal`` rows that look identical to a reader.
    """

    try:
        with single_flight("market-pulse", MARKET_PULSE_LOCK_TTL_SECONDS):
            return _refresh_market_pulse_locked()
    except AlreadyRunning:
        LOGGER.warning("Market pulse already running; skipping this window")
        return {"status": "skipped", "reason": "already running"}


def _refresh_market_pulse_locked() -> dict[str, Any]:
    with session_scope(session_factory()) as db:
        posts = db.scalars(
            select(MarketPost)
            .order_by(MarketPost.published_at.desc().nullslast())
            .limit(50)
        ).all()
        if not posts:
            return {"status": "empty", "signals": 0}
        by_url = {post.source_url: post for post in posts}
        provider = get_model_provider()
        with postgres_checkpointer() as checkpointer:
            graph = build_market_pulse_graph(provider, checkpointer)
            result = graph.invoke(
                {
                    "posts": [
                        {
                            "company": post.company_name,
                            "content": post.content,
                            "published_at": post.published_at,
                            "source_url": post.source_url,
                        }
                        for post in posts
                    ]
                },
                config={
                    "configurable": {
                        "thread_id": f"market:{datetime.now(UTC).date().isoformat()}"
                    }
                },
            )
        created = 0
        for signal in result.get("signals", []):
            cited_ids = [
                str(by_url[url].id)
                for url in signal.get("citations", [])
                if url in by_url
            ]
            if not cited_ids:
                continue
            db.add(
                MarketSignal(
                    topic=str(signal.get("topic") or "Hiring activity")[:256],
                    summary=str(signal.get("summary") or "")[:10000],
                    company_name=signal.get("company_name"),
                    role_tags=signal.get("role_tags", []),
                    confidence=max(0.0, min(1.0, float(signal.get("confidence", 0.5)))),
                    citation_post_ids=cited_ids,
                    valid_until=datetime.now(UTC) + timedelta(days=14),
                )
            )
            created += 1
        return {"status": "ready" if created else "review", "signals": created}


@celery_app.task(
    name="hope.matching.profile",
    autoretry_for=LLM_RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_jitter=True,
    retry_backoff_max=LLM_RETRY_BACKOFF_MAX_SECONDS,
    max_retries=3,
)
def generate_profile_matches(profile_id: str) -> dict[str, Any]:
    with session_scope(session_factory()) as db:
        profile = db.get(StudentProfileRecord, UUID(profile_id))
        if profile is None:
            return {"status": "missing", "profile_id": profile_id}
        consent = db.scalar(
            select(ConsentRecord)
            .where(
                ConsentRecord.user_id == profile.user_id,
                ConsentRecord.withdrawn_at.is_(None),
            )
            .order_by(ConsentRecord.accepted_at.desc())
            .limit(1)
        )
        if consent is None or not consent.ai_matching:
            return {"status": "consent-required", "profile_id": profile_id}

        profile_payload = dict(profile.profile_json or {})
        profile_payload.setdefault("student_id", str(profile.id))
        profile_payload.setdefault("name", profile.name or "Student")
        profile_payload.setdefault("concentration", profile.concentration or "MSIS")
        profile_payload.setdefault("academic_stage", profile.stage)
        profile_payload.setdefault("skills", profile.skills or [])
        profile_payload.setdefault("target_roles", profile.interests or [])
        student = StudentProfile.model_validate(profile_payload)
        records = db.scalars(
            select(JobPostingRecord).where(
                JobPostingRecord.status == "active",
                (
                    JobPostingRecord.application_deadline.is_(None)
                    | (JobPostingRecord.application_deadline >= date.today())
                ),
            )
        ).all()
        records_by_id = {record.id: record for record in records if record.description}
        domain_by_id = {
            job_id: job_from_record(record) for job_id, record in records_by_id.items()
        }
        deterministic = rank_jobs_for_student(student, list(domain_by_id.values()))
        all_rule_by_id = {
            UUID(match.job.raw_metadata["database_id"]): match
            for match in deterministic
        }
        deterministic_ids = set(list(all_rule_by_id)[:100])

        provider = get_model_provider()
        vector_by_id: dict[UUID, float] = {}
        try:
            profile_text = "\n".join(
                [
                    student.concentration,
                    " ".join(student.target_roles),
                    " ".join(student.skills),
                    " ".join(student.geo_preference),
                ]
            )
            vector = provider.embed([query_embedding_text(profile_text)])[0]
            if _usable_vector(vector, "student profile"):
                vector_by_id = {
                    job.id: similarity
                    for job, similarity in EmbeddingRepository(db).similarity_search(
                        vector,
                        filters={"status": "active"},
                        limit=100,
                        embedding_model=get_platform_settings().embedding_model,
                    )
                }
        except ModelUnavailable, IndexError:
            pass

        candidate_ids = deterministic_ids | set(vector_by_id)
        candidates = sorted(
            candidate_ids,
            key=lambda job_id: (
                0.5625
                * normalize_rule_score(
                    all_rule_by_id[job_id].score if job_id in all_rule_by_id else 0.0
                )
                + 0.4375 * vector_by_id.get(job_id, 0.0)
            ),
            reverse=True,
        )[:50]
        db.execute(
            delete(JobMatchRecord).where(JobMatchRecord.student_id == profile.id)
        )

        student_context = _student_context(student)
        enrichment_by_id = _enrichment_payloads(db, candidates)
        inputs: list[dict[str, Any]] = [
            {
                "student_id": profile_id,
                "job_id": str(job_id),
                "rule_score": (
                    all_rule_by_id[job_id].score if job_id in all_rule_by_id else 0.0
                ),
                "vector_score": vector_by_id.get(job_id, 0.0),
                "evidence": (
                    all_rule_by_id[job_id].reasons if job_id in all_rule_by_id else []
                ),
                "student": student_context,
                "job": _job_context(
                    records_by_id[job_id], enrichment_by_id.get(job_id)
                ),
            }
            for job_id in candidates
            if job_id in records_by_id
        ]

        # No checkpointer here, unlike the enrichment and market-pulse graphs.
        # This one is a single stateless node with no retry loop, so a
        # checkpoint buys no resumability -- it writes ~50 threads of student
        # data per profile for a computation that is cheaper to redo than to
        # resume. Leaving it out is also what makes the fan-out below safe:
        # PostgresSaver wraps one connection, and sharing it across threads is
        # not something LangGraph promises.
        graph = build_match_generation_graph(provider)
        results = _score_matches_concurrently(graph, inputs, provider.max_parallel)

        degraded = 0
        for state, result in zip(inputs, results, strict=True):
            job_id = UUID(str(state["job_id"]))
            is_degraded = bool(result["degraded"])
            degraded += int(is_degraded)
            evidence = list(state["evidence"])
            db.add(
                JobMatchRecord(
                    student_id=profile.id,
                    job_id=job_id,
                    match_score=result["final_score"],
                    llm_score=result.get("llm_score"),
                    vector_score=vector_by_id.get(job_id),
                    rule_score=state["rule_score"],
                    explanation=result["explanation"],
                    ranking_version="hybrid-v1",
                    status="degraded" if is_degraded else "ready",
                    metadata_json={"evidence": evidence[:5]},
                )
            )
        return {
            "status": "ready" if degraded == 0 else "degraded",
            "profile_id": profile_id,
            "matches": len(inputs),
            "awaiting_ai_refinement": degraded,
        }


def _score_matches_concurrently(
    graph: CompiledStateGraph[Any, Any, Any],
    inputs: list[dict[str, Any]],
    max_parallel: int,
) -> list[dict[str, Any]]:
    """Invoke ``graph`` over every input, keeping the server's slots busy.

    Scoring 50 candidates one at a time meant a student waited the sum of 50
    generations. The pool is sized to the server's decode slots because more
    in-flight requests than that only queue inside Ollama.

    Results come back in input order so the caller can zip them against the
    state that produced them. Database writes stay with the caller: the
    SQLAlchemy Session is not thread-safe.
    """

    if not inputs:
        return []
    workers = max(1, min(max_parallel, len(inputs)))
    if workers == 1:
        return [graph.invoke(dict(state)) for state in inputs]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda state: graph.invoke(dict(state)), inputs))


def _student_context(student: StudentProfile) -> dict[str, Any]:
    """The profile fields a fit judgement can legitimately rest on.

    Deliberately narrow: work authorization and other protected attributes are
    excluded, so the reranker cannot weigh them even implicitly.
    """

    return {
        "concentration": student.concentration,
        "academic_stage": student.academic_stage,
        "target_roles": student.target_roles,
        "skills": student.skills,
        "location_preferences": student.geo_preference,
    }


def _job_context(
    record: JobPostingRecord, enrichment: dict[str, Any] | None
) -> dict[str, Any]:
    """The posting as the model should see it, bounded so the prompt fits."""

    context: dict[str, Any] = {
        "title": record.title,
        "company": record.company_name,
        "location": record.location,
        "employment_type": record.employment_type,
        "seniority": record.seniority,
        "description": (record.description or "")[:6000],
    }
    if enrichment:
        # Already-extracted structure beats making the model re-derive it from
        # the same description it is reading anyway.
        context["extracted_skills"] = enrichment.get("skills", [])[:20]
        context["extracted_requirements"] = enrichment.get("requirements", [])[:20]
    return context


def _enrichment_payloads(
    db: Session, job_ids: list[UUID]
) -> dict[UUID, dict[str, Any]]:
    """Load ready enrichment payloads for ``job_ids`` in one query."""

    if not job_ids:
        return {}
    rows = db.scalars(
        select(JobEnrichment).where(
            JobEnrichment.job_id.in_(job_ids),
            JobEnrichment.version == "enrichment-v1",
            JobEnrichment.status == "ready",
        )
    ).all()
    return {row.job_id: dict(row.payload or {}) for row in rows}


@celery_app.task(name="hope.privacy.retention")
def enforce_retention() -> dict[str, Any]:
    cutoff = datetime.now(UTC) - timedelta(days=90)
    deleted_users: set[UUID] = set()
    with session_scope(session_factory()) as db:
        profiles = db.scalars(
            select(StudentProfileRecord).where(
                StudentProfileRecord.program_exit_at.is_not(None),
                StudentProfileRecord.program_exit_at < cutoff,
            )
        ).all()
        for profile in profiles:
            if profile.user_id is None:
                continue
            deleted_users.add(profile.user_id)
        requests = db.scalars(
            select(DeletionRequest).where(DeletionRequest.status == "queued")
        ).all()
        for request in requests:
            deleted_users.add(request.user_id)
        for user_id in deleted_users:
            _purge_user(db, user_id)
        quarantine_result = db.execute(
            delete(SourceQuarantineRecord).where(
                SourceQuarantineRecord.expires_at < datetime.now(UTC)
            )
        )
        quarantined = int(getattr(quarantine_result, "rowcount", 0) or 0)
        return {
            "retained_aggregate_only": len(deleted_users),
            "deletion_requests": len(requests),
            "quarantine_records": quarantined,
        }


def _purge_user(db: Session, user_id: UUID) -> None:
    documents = db.scalars(
        select(ResumeDocument).where(ResumeDocument.user_id == user_id)
    ).all()
    for document in documents:
        delete_private_document(document.object_key)
    thread_ids = db.scalars(
        select(CoachThread.id).where(CoachThread.user_id == user_id)
    ).all()
    for thread_id in thread_ids:
        delete_checkpoint_thread(f"coach:{thread_id}")
    profile_ids = db.scalars(
        select(StudentProfileRecord.id).where(StudentProfileRecord.user_id == user_id)
    ).all()
    if profile_ids:
        db.execute(
            delete(JobMatchRecord).where(JobMatchRecord.student_id.in_(profile_ids))
        )
    db.execute(delete(User).where(User.id == user_id))

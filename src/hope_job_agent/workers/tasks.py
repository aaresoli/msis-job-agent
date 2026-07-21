"""Idempotent background tasks for AI enrichment, matching, and retention."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from docx import Document
from pypdf import PdfReader
from sqlalchemy import delete, select

from hope_job_agent.ai.checkpoints import (
    delete_checkpoint_thread,
    postgres_checkpointer,
)
from hope_job_agent.ai.graphs import (
    build_job_enrichment_graph,
    build_market_pulse_graph,
    build_match_generation_graph,
)
from hope_job_agent.ai.provider import ModelUnavailable, get_model_provider
from hope_job_agent.ai.ranking import normalize_rule_score
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
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.persistence.embedding_repository import EmbeddingRepository
from hope_job_agent.persistence.source_run_repository import SourceRunRepository
from hope_job_agent.pipeline.run_mvp import MvpPipelineError, run_mvp_pipeline
from hope_job_agent.pipeline.run_posts import ingest_market_posts
from hope_job_agent.platform.documents import (
    delete_private_document,
    get_private_document,
)
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


def _factory():
    return create_session_factory(create_db_engine(storage="postgres"))


@celery_app.task(
    name="hope.enrichment.job",
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    max_retries=3,
)
def enrich_job(job_id: str) -> dict:
    with session_scope(_factory()) as db:
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
            model=provider.health().model,
        )
        row.skills = payload.get("skills", [])
        row.requirements = payload.get("requirements", [])
        row.work_auth_evidence = payload.get("work_auth_evidence", [])
        row.confidence = payload.get("confidence")
        row.status = result.get("status", "review")
        row.payload = payload
        try:
            embedding_input = f"{job.title}\n{job.description or ''}"
            vector = provider.embed([embedding_input])[0]
            if len(vector) == 768:
                EmbeddingRepository(db).upsert_embedding(
                    job.id,
                    vector,
                    "embeddinggemma",
                    hashlib.sha256(embedding_input.encode()).hexdigest(),
                )
        except (ModelUnavailable, IndexError):
            pass
        if existing is None:
            db.add(row)
        return {"status": row.status, "job_id": job_id}


@celery_app.task(
    bind=True,
    name="hope.sources.refresh",
    acks_late=False,
    max_retries=0,
    time_limit=5400,
    soft_time_limit=5100,
)
def refresh_source(
    self,  # noqa: ANN001 - Celery binds the task instance
    source_name: str,
    limit: int | None = None,
    dry_run: bool = False,
    full_refresh: bool = False,
) -> dict:
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
        with session_scope(_factory()) as db:
            runs = SourceRunRepository(db)
            run = runs.start_run(source_name, metadata={"trigger": "scheduled"})
            runs.fail_run(run.id, error[:4096])
    except Exception:  # noqa: BLE001 - never mask the original pipeline failure
        LOGGER.exception("Could not record failed source run for %s", source_name)


@celery_app.task(name="hope.enrichment.resume")
def parse_resume(resume_id: str) -> dict:
    with session_scope(_factory()) as db:
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
        try:
            response = get_model_provider().chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Extract a proposed student profile using only resume "
                            "evidence. Do not infer work authorization or private "
                            "attributes. Return JSON."
                        ),
                    },
                    {"role": "user", "content": text[:30000]},
                ],
                schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "skills": {"type": "array", "items": {"type": "string"}},
                        "target_roles": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["skills", "target_roles", "evidence"],
                },
            )
            resume.parsed_profile = json.loads(response)
            resume.parse_status = "review"
        except (ModelUnavailable, json.JSONDecodeError) as exc:
            resume.parse_status = "awaiting_local_ai"
            resume.parsed_profile = {"warning": str(exc)}
        return {"status": resume.parse_status, "resume_id": resume_id}


@celery_app.task(name="hope.sources.refresh_posts")
def refresh_posts(
    dataset_id: str | None = None,
    run_id: str | None = None,
    trigger_run: bool = False,
    max_items: int | None = None,
    enqueue_pulse: bool = True,
) -> dict:
    """Fetch LinkedIn hiring posts from Apify and refresh market signals.

    Runs on the ``ingest`` queue. Ingests MSIS-relevant posts into
    ``market_posts`` then enqueues :func:`refresh_market_pulse` so the LLM
    signal extraction picks up the new posts. :func:`refresh_all` passes
    ``enqueue_pulse=False`` because it runs the pulse itself once every source
    has landed.
    """

    with session_scope(_factory()) as db:
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
    self,  # noqa: ANN001 - Celery binds the task instance
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
) -> dict:
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
    """

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

    signals: dict | None = None
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


def _refresh_job_source(source_name: str, **options) -> dict:  # noqa: ANN003
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


def _refresh_posts_source(**options) -> dict:  # noqa: ANN003
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


def _refresh_signals() -> dict:
    """Re-extract market signals; a local-model outage degrades, not fails."""

    try:
        return refresh_market_pulse.run()
    except Exception as exc:  # noqa: BLE001 - signals are best-effort
        LOGGER.exception("refresh_all: market pulse failed")
        return {"status": "failed", "error": str(exc)[:4096]}


def _start_orchestrator_run(metadata: dict) -> UUID | None:
    try:
        with session_scope(_factory()) as db:
            run = SourceRunRepository(db).start_run(
                ORCHESTRATOR_SOURCE, metadata=metadata
            )
            return run.id
    except Exception:  # noqa: BLE001 - the sweep is still worth running
        LOGGER.exception("refresh_all: could not open the parent source run")
        return None


def _finish_orchestrator_run(
    run_id: UUID | None,
    summary: dict,
    *,
    failed: bool,
) -> None:
    if run_id is None:
        return
    try:
        with session_scope(_factory()) as db:
            runs = SourceRunRepository(db)
            # finish_run stores the per-source summary and marks the run
            # partial_success when any source errored; a sweep where nothing
            # succeeded is downgraded to failed for source-health alerting.
            runs.finish_run(run_id, summary=summary)
            if failed:
                runs.fail_run(run_id, "; ".join(summary["errors"])[:4096])
    except Exception:  # noqa: BLE001 - never mask per-source outcomes
        LOGGER.exception("refresh_all: could not close the parent source run")


@celery_app.task(name="hope.market.refresh")
def refresh_market_pulse() -> dict:
    with session_scope(_factory()) as db:
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


@celery_app.task(name="hope.matching.profile")
def generate_profile_matches(profile_id: str) -> dict:
    with session_scope(_factory()) as db:
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
        domain_by_id = {
            record.id: _job_from_record(record)
            for record in records
            if record.description
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
            vector = provider.embed([profile_text])[0]
            if len(vector) == 768:
                vector_by_id = {
                    job.id: similarity
                    for job, similarity in EmbeddingRepository(db).similarity_search(
                        vector, filters={"status": "active"}, limit=100
                    )
                }
        except (ModelUnavailable, IndexError):
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
        degraded = 0
        with postgres_checkpointer() as checkpointer:
            graph = build_match_generation_graph(provider, checkpointer)
            for job_id in candidates:
                match = all_rule_by_id.get(job_id)
                evidence = match.reasons if match else []
                result = graph.invoke(
                    {
                        "student_id": profile_id,
                        "job_id": str(job_id),
                        "rule_score": match.score if match else 0.0,
                        "vector_score": vector_by_id.get(job_id, 0.0),
                        "evidence": evidence,
                    },
                    config={
                        "configurable": {"thread_id": f"match:{profile_id}:{job_id}"}
                    },
                )
                is_degraded = bool(result["degraded"])
                degraded += int(is_degraded)
                db.add(
                    JobMatchRecord(
                        student_id=profile.id,
                        job_id=job_id,
                        match_score=result["final_score"],
                        llm_score=result.get("llm_score"),
                        vector_score=vector_by_id.get(job_id),
                        rule_score=match.score if match else 0.0,
                        explanation=result["explanation"],
                        ranking_version="hybrid-v1",
                        status="degraded" if is_degraded else "ready",
                        metadata_json={"evidence": evidence[:5]},
                    )
                )
        return {
            "status": "ready" if degraded == 0 else "degraded",
            "profile_id": profile_id,
            "matches": len(candidates),
            "awaiting_ai_refinement": degraded,
        }


def _job_from_record(record: JobPostingRecord) -> JobPosting:
    return JobPosting(
        source=record.source,
        source_job_id=record.external_job_id,
        title=record.title,
        company=record.company_name,
        location=record.location or "Not specified",
        description=record.description or "Description not supplied",
        url=(
            record.apply_url
            or record.source_url
            or record.canonical_url
            or f"https://unavailable.invalid/jobs/{record.id}"
        ),
        posted_date=record.posted_at,
        employment_type=record.employment_type,
        seniority=record.seniority,
        concentration_tags=record.concentration_tags or [],
        opt_cpt_flag=record.opt_cpt_flag,
        source_detail=record.source_detail,
        apply_url=record.apply_url,
        application_deadline=record.application_deadline,
        compensation=record.compensation,
        raw_metadata={"database_id": str(record.id)},
    )


@celery_app.task(name="hope.privacy.retention")
def enforce_retention() -> dict:
    cutoff = datetime.now(UTC) - timedelta(days=90)
    deleted_users: set[UUID] = set()
    with session_scope(_factory()) as db:
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


def _purge_user(db, user_id: UUID) -> None:
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

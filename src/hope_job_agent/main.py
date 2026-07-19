"""FastAPI application for the HOPE career-intelligence platform."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from hope_job_agent import __version__
from hope_job_agent.ai.provider import get_model_provider
from hope_job_agent.api import (
    applications,
    auth,
    coach,
    gcs,
    internal,
    jobs,
    market,
    student,
)
from hope_job_agent.platform.observability import configure_observability
from hope_job_agent.platform.settings import get_platform_settings


def create_app() -> FastAPI:
    settings = get_platform_settings()
    application = FastAPI(
        title="Kelley HOPE MSIS Career Intelligence",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_base_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "Idempotency-Key",
            "X-Request-ID",
        ],
    )
    Instrumentator(excluded_handlers=["/metrics"]).instrument(application).expose(
        application, include_in_schema=False
    )
    configure_observability(application)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path.startswith("/api/v1"):
            response.headers["Cache-Control"] = "no-store"
        return response

    application.include_router(auth.router, prefix="/api/v1")
    application.include_router(student.router, prefix="/api/v1")
    application.include_router(jobs.router, prefix="/api/v1")
    application.include_router(applications.router, prefix="/api/v1")
    application.include_router(coach.router, prefix="/api/v1")
    application.include_router(market.router, prefix="/api/v1")
    application.include_router(gcs.router, prefix="/api/v1")
    application.include_router(internal.router)

    @application.get("/health")
    @application.get("/health/live")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.get("/health/ready")
    def readiness() -> JSONResponse:
        model = get_model_provider().health()
        payload = {
            "status": "ready",
            "model": {
                "available": model.available,
                "provider": model.provider,
                "model": model.model,
                "detail": model.detail,
            },
            "degraded": not model.available,
        }
        return JSONResponse(payload, status_code=200)

    return application


app = create_app()

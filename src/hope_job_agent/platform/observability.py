"""Redacted OpenTelemetry setup for the self-hosted Phoenix collector."""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from hope_job_agent.platform.settings import get_platform_settings


def configure_observability(app: FastAPI) -> None:
    endpoint = get_platform_settings().otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "hope-career-api",
                "service.namespace": "hope-private",
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        )
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health.*,metrics",
        tracer_provider=provider,
    )

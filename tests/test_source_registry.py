import pytest

from hope_job_agent.pipeline.runner import run_pipeline
from hope_job_agent.sources.handshake import HandshakeSource
from hope_job_agent.sources.ksbit_export import KSBIT_SOURCE_NAME, KsbitExportSource
from hope_job_agent.sources.linkedin_reference import LinkedInReferenceSource
from hope_job_agent.sources.registry import (
    SOURCE_REGISTRY,
    SourceComplianceError,
    SourceStatus,
    create_source_adapter,
    ensure_source_allowed,
)


def test_registry_marks_restricted_sources_as_not_runnable():
    assert SOURCE_REGISTRY["handshake"].status is SourceStatus.RESTRICTED
    assert SOURCE_REGISTRY["linkedin_reference"].status is SourceStatus.MANUAL_REFERENCE

    with pytest.raises(SourceComplianceError):
        ensure_source_allowed("handshake")


def test_pipeline_refuses_restricted_sources(tmp_path):
    with pytest.raises(SourceComplianceError):
        run_pipeline([HandshakeSource()], output_path=tmp_path / "out.json")

    with pytest.raises(SourceComplianceError):
        run_pipeline([LinkedInReferenceSource()], output_path=tmp_path / "out.json")


def test_registry_constructs_ksbit_export_adapter():
    metadata = ensure_source_allowed(KSBIT_SOURCE_NAME)
    source = create_source_adapter(
        KSBIT_SOURCE_NAME,
        "data/sample_ksbit_jobs.json",
        source_since_date="2026-06-01",
        source_limit=2,
    )

    assert SOURCE_REGISTRY[KSBIT_SOURCE_NAME].status is SourceStatus.APPROVED
    assert metadata.name == KSBIT_SOURCE_NAME
    assert metadata.display_name == "KSBIT / 12Twenty Local Export"
    assert "JSON/CSV/XLSX" in metadata.access_method
    assert "raw_metadata" in metadata.notes
    assert isinstance(source, KsbitExportSource)
    assert source.source_name == KSBIT_SOURCE_NAME


def test_source_factory_rejects_unknown_restricted_and_unsupported_sources():
    with pytest.raises(SourceComplianceError, match="not registered"):
        create_source_adapter("not_a_source", "data/sample_ksbit_jobs.json")

    with pytest.raises(SourceComplianceError, match="cannot run"):
        create_source_adapter("handshake", "data/sample_ksbit_jobs.json")

    with pytest.raises(SourceComplianceError, match="cannot be constructed"):
        create_source_adapter("employer_careers", "data/sample_ksbit_jobs.json")


def test_source_factory_rejects_ksbit_options_for_approved_json():
    with pytest.raises(SourceComplianceError, match="only supported for ksbit_export"):
        create_source_adapter(
            "approved_json",
            "docs/examples/approved_jobs.sample.json",
            source_since_date="2026-06-01",
        )

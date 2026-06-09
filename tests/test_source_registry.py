import pytest

from hope_job_agent.pipeline.runner import run_pipeline
from hope_job_agent.sources.handshake import HandshakeSource
from hope_job_agent.sources.linkedin_reference import LinkedInReferenceSource
from hope_job_agent.sources.registry import (
    SOURCE_REGISTRY,
    SourceComplianceError,
    SourceStatus,
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

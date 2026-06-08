"""Classification helpers for MSIS role and concentration tagging."""

from hope_job_agent.classification.classifier import (
    JobClassification,
    classify_job,
    classify_job_posting,
)
from hope_job_agent.classification.taxonomy import (
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
)

__all__ = [
    "JobClassification",
    "MSIS_CONCENTRATIONS",
    "MSIS_TARGET_ROLES",
    "classify_job",
    "classify_job_posting",
]

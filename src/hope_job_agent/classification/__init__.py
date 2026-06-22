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
from hope_job_agent.classification.work_authorization import (
    WorkAuthorizationDetection,
    WorkAuthorizationLLMClassifier,
    detect_work_authorization,
)

__all__ = [
    "JobClassification",
    "MSIS_CONCENTRATIONS",
    "MSIS_TARGET_ROLES",
    "WorkAuthorizationDetection",
    "WorkAuthorizationLLMClassifier",
    "classify_job",
    "classify_job_posting",
    "detect_work_authorization",
]

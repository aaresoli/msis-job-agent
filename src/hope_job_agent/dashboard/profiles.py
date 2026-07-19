"""Sample student profile loading for the demo dashboard."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from hope_job_agent.models.student import StudentProfile
from hope_job_agent.utils.hashing import stable_hash

LOGGER = logging.getLogger(__name__)

DEFAULT_PROFILES_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "sample_profiles.json"
)


def profile_key(profile: StudentProfile) -> str:
    """Stable identifier used in dashboard URLs."""

    if profile.student_id and profile.student_id.strip():
        return profile.student_id.strip()
    return stable_hash(profile.name)[:10]


def load_profiles(path: Path | None = None) -> dict[str, StudentProfile]:
    """Load consenting sample profiles keyed by student id.

    Returns an empty mapping (with a logged warning) when the file is missing
    or malformed so the dashboard still works as a plain job board.
    """

    profiles_path = path or DEFAULT_PROFILES_PATH
    try:
        payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Dashboard could not load profiles %s: %s", profiles_path, exc)
        return {}

    records = payload.get("profiles") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        LOGGER.warning("Profiles file %s has an unexpected shape", profiles_path)
        return {}

    profiles: dict[str, StudentProfile] = {}
    for record in records:
        try:
            profile = StudentProfile.model_validate(record)
        except ValidationError as exc:
            LOGGER.warning(
                "Dashboard skipped invalid profile: %s",
                exc.errors()[0].get("msg") if exc.errors() else exc,
            )
            continue
        if not profile.ai_matching_consent:
            continue
        profiles[profile_key(profile)] = profile
    return profiles

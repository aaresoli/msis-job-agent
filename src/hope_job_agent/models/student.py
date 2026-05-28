"""Student profile model used for matching and ranking."""

from pydantic import BaseModel, Field


class StudentProfile(BaseModel):
    """Minimal student profile for early matching experiments."""

    name: str
    concentration: str
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    stage: str

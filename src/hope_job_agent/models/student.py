"""Student profile model used for matching and ranking."""

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudentProfile(BaseModel):
    """Student profile fields consumed by v0 matching and ranking."""

    name: str = Field(min_length=1)
    concentration: str = Field(min_length=1)
    academic_stage: str | None = None
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    stage: str | None = None
    work_auth_status: str | None = None
    opt_eligibility_date: date | None = None
    geo_preference: list[str] = Field(default_factory=list)
    remote_preference: str | None = None
    delivery_preference: str | None = None
    match_frequency: str = "Once a day"
    ai_matching_consent: bool = True
    profile_version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def fill_stage_alias(self) -> "StudentProfile":
        """Keep legacy `stage` tests compatible with the richer profile schema."""

        if self.academic_stage is None and self.stage is not None:
            self.academic_stage = self.stage
        if self.stage is None and self.academic_stage is not None:
            self.stage = self.academic_stage
        return self

    @property
    def needs_cpt_opt(self) -> bool:
        """Return whether this profile needs CPT/OPT-friendly opportunities."""

        return self.work_auth_status == "Need CPT / OPT sponsorship"

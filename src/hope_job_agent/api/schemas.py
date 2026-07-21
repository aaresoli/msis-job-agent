"""Public API request and response contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(ApiModel):
    message: str


class MagicLinkRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)


class MagicLinkConsume(ApiModel):
    token: str = Field(min_length=32, max_length=512)


class SessionResponse(ApiModel):
    user_id: UUID
    email: str
    display_name: str | None
    role: str
    csrf_token: str | None = None


class ProfileUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=256)
    concentration: str = Field(min_length=1, max_length=256)
    academic_stage: str | None = Field(default=None, max_length=128)
    target_roles: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=100)
    work_auth_status: str | None = Field(default=None, max_length=128)
    geo_preference: list[str] = Field(default_factory=list, max_length=30)
    remote_preference: str | None = Field(default=None, max_length=128)
    delivery_preference: str | None = Field(default=None, max_length=128)
    match_frequency: str = Field(default="Once a day", max_length=64)
    program_exit_at: datetime | None = None


class ResumeConfirm(ApiModel):
    accepted_profile: ProfileUpdate


class ConsentCreate(ApiModel):
    policy_version: str = Field(min_length=1, max_length=64)
    ai_matching: bool


class SharingGrantCreate(ApiModel):
    advisor_user_id: UUID
    scope: list[Literal["profile", "applications", "resume", "coach"]]
    expires_at: datetime


class JobFeedbackCreate(ApiModel):
    action: Literal["saved", "dismissed", "applied", "opened"]
    reason: str | None = Field(default=None, max_length=256)


class ApplicationCreate(ApiModel):
    job_id: UUID | None = None
    company_name: str = Field(min_length=1, max_length=512)
    role_title: str = Field(min_length=1, max_length=512)
    status: Literal[
        "saved", "preparing", "applied", "interview", "offer", "rejected", "withdrawn"
    ] = "saved"
    notes: str | None = Field(default=None, max_length=10000)
    deadline: date | None = None
    external_url: HttpUrl | None = None


class ApplicationUpdate(ApiModel):
    status: Literal[
        "saved", "preparing", "applied", "interview", "offer", "rejected", "withdrawn"
    ]
    notes: str | None = Field(default=None, max_length=10000)
    deadline: date | None = None


class CoachMessageCreate(ApiModel):
    content: str = Field(min_length=1, max_length=8000)


class SourceRunRequest(ApiModel):
    since: datetime | None = None
    # Caps ranked matches per profile; it does NOT bound how much a source
    # fetches. Use max_companies for that.
    limit: int | None = Field(default=None, ge=1, le=10000)
    # company_careers only: sweep at most this many enabled employers, highest
    # priority first. The bound operators want when exercising a deployment.
    max_companies: int | None = Field(default=None, ge=1, le=10000)
    dry_run: bool = False


class BatchRequest(ApiModel):
    ids: list[UUID] = Field(default_factory=list, max_length=1000)


class ApifyWebhook(ApiModel):
    event_id: str = Field(min_length=1, max_length=256)
    actor_run_id: str = Field(min_length=1, max_length=256)
    dataset_id: str | None = Field(default=None, max_length=256)
    resource_type: Literal["job", "post"]
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)

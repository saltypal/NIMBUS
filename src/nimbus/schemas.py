"""Public contracts: models propose fields; these schemas constrain them."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(StrEnum):
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    MAINTENANCE = "maintenance"


class Status(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"


class Action(StrEnum):
    REPORT = "report_fault"
    OBSERVATION = "record_observation"
    INSPECTION = "record_inspection"
    START = "start_work"
    WORK = "record_work"
    REVIEW = "submit_for_review"
    VERIFY = "submit_verification"
    ACKNOWLEDGE = "acknowledge_handover"
    REOPEN = "reopen"


class Actor(StrictModel):
    person_id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=160)
    role: Role


class Capture(StrictModel):
    client_operation_id: str = Field(min_length=1, max_length=160)
    actor: Actor
    shift_id: str = Field(min_length=1, max_length=160)
    machine_id: str
    action: Action
    source_type: Literal["text", "audio", "handwriting"] = "text"
    ticket_id: str | None = None
    expected_ticket_version: int | None = None
    observed_at: datetime | None = None
    purpose: Literal["report", "clarification"] = "report"
    parent_submission_id: str | None = None
    manual_fields: dict = Field(default_factory=dict)
    use_ai: bool | None = None

    @field_validator("observed_at")
    @classmethod
    def aware_observation(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Observation time must include a timezone.")
        return value


class Confirmation(StrictModel):
    operation_id: str = Field(min_length=1, max_length=160)
    draft_revision: int = Field(ge=1)
    text_revision: int = Field(ge=1)
    expected_processing_version: int = Field(ge=1)
    expected_ticket_version: int | None = None
    reviewed_by: Actor
    fields: dict


class RequiredCheck(StrictModel):
    check_id: str
    required_result: Literal["pass"] = "pass"
    minimum_cycles: int | None = Field(default=None, ge=1)
    minimum_duration_seconds: float | None = Field(default=None, gt=0)
    required_condition: str | None = None


class Policy(StrictModel):
    source_id: str
    document_type: Literal["verification_policy"]
    policy_version: int = Field(ge=1)
    approval_status: Literal["approved", "approved_demo", "revoked", "draft"]
    machine_types: list[str] = Field(min_length=1)
    required_checks: list[RequiredCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_checks(self):
        ids = [check.check_id for check in self.required_checks]
        if len(set(ids)) != len(ids):
            raise ValueError("Policy check IDs must be unique.")
        return self


class CheckEvidence(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    check_id: str
    result: Literal["pass", "fail", "unknown", "skipped"]
    evidence_text: str = Field(min_length=1, max_length=4000)
    cycles: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    condition: str | None = None
    fault_present: bool | None = None


class Citation(StrictModel):
    source_id: str
    chunk_id: str


class Draft(StrictModel):
    fields: dict = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    summary: str = ""
    suggestions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    field_evidence: dict[str, str] = Field(default_factory=dict)

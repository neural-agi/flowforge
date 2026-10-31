"""Typed domain models for persisted workflow state."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepSpecification:
    name: str
    order: int
    input: dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("step name must not be empty")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")


@dataclass(frozen=True, slots=True)
class WorkflowSpecification:
    definition_name: str
    definition_version: str
    input: dict[str, Any]
    steps: tuple[StepSpecification, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("workflow must have at least one step")
        names = [step.name for step in self.steps]
        if len(names) != len(set(names)):
            raise ValueError("step names must be unique")
        expected_orders = list(range(1, len(self.steps) + 1))
        if [step.order for step in self.steps] != expected_orders:
            raise ValueError("step order must be consecutive and start at 1")


@dataclass(frozen=True, slots=True)
class PersistedWorkflowSummary:
    id: UUID
    definition_name: str
    definition_version: str
    idempotency_key: str
    status: WorkflowStatus
    input: dict[str, Any]
    output: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PersistedWorkflowStep:
    id: UUID
    workflow_id: UUID
    step_name: str
    step_order: int
    status: StepStatus
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    input: dict[str, Any]
    output: dict[str, Any] | None
    last_error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ClaimedStep:
    step: PersistedWorkflowStep
    attempt_number: int
    worker_id: str


@dataclass(frozen=True, slots=True)
class WorkflowHistoryEvent:
    id: int
    workflow_id: UUID
    workflow_step_id: UUID | None
    event_type: str
    details: dict[str, Any]
    created_at: datetime

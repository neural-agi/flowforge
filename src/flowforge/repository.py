"""Explicit SQL repository for durable workflow state."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from .database import transaction
from .models import (
    ClaimedStep,
    PersistedWorkflowStep,
    PersistedWorkflowSummary,
    StepSpecification,
    StepStatus,
    WorkflowHistoryEvent,
    WorkflowSpecification,
    WorkflowStatus,
)


class RepositoryError(RuntimeError):
    """Base class for repository/domain errors."""


class IdempotencyConflictError(RepositoryError):
    """The workflow idempotency key was reused with different input."""


class LeaseLostError(RepositoryError):
    """A worker no longer owns the step lease it tried to update."""


class WorkflowRepository:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings

    def create_workflow(
        self,
        definition_name: str,
        definition_version: str,
        idempotency_key: str,
        workflow_input: dict[str, Any],
        steps: Sequence[StepSpecification],
    ) -> PersistedWorkflowSummary:
        specification = WorkflowSpecification(
            definition_name, definition_version, workflow_input, tuple(steps)
        )
        workflow_id = uuid4()
        try:
            with transaction(self.settings) as connection:
                existing = connection.execute(
                    """
                    SELECT * FROM workflows WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    if (
                        existing["definition_name"] != specification.definition_name
                        or existing["definition_version"] != specification.definition_version
                        or existing["input"] != specification.input
                    ):
                        raise IdempotencyConflictError(
                            f"workflow idempotency key already used: {idempotency_key}"
                        )
                    return _workflow_from_row(existing)

                row = connection.execute(
                    """
                    INSERT INTO workflows
                        (id, definition_name, definition_version, idempotency_key, status, input)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        workflow_id,
                        specification.definition_name,
                        specification.definition_version,
                        idempotency_key,
                        WorkflowStatus.RUNNING,
                        Jsonb(specification.input),
                    ),
                ).fetchone()
                for step in specification.steps:
                    connection.execute(
                        """
                        INSERT INTO workflow_steps
                            (id, workflow_id, step_name, step_order, status, max_attempts, input)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            uuid4(),
                            workflow_id,
                            step.name,
                            step.order,
                            StepStatus.PENDING,
                            step.max_attempts,
                            Jsonb(step.input),
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO workflow_events (workflow_id, event_type, details)
                    VALUES (%s, 'workflow_started', %s)
                    """,
                    (workflow_id, Jsonb({"definition_name": specification.definition_name})),
                )
                return _workflow_from_row(row)
        except UniqueViolation as exc:
            raise IdempotencyConflictError(
                f"workflow idempotency key already used: {idempotency_key}"
            ) from exc

    def get_workflow(
        self, workflow_id: UUID
    ) -> tuple[PersistedWorkflowSummary, list[PersistedWorkflowStep]] | None:
        with transaction(self.settings) as connection:
            workflow = connection.execute(
                "SELECT * FROM workflows WHERE id = %s", (workflow_id,)
            ).fetchone()
            if not workflow:
                return None
            steps = connection.execute(
                "SELECT * FROM workflow_steps WHERE workflow_id = %s ORDER BY step_order",
                (workflow_id,),
            ).fetchall()
            return _workflow_from_row(workflow), [_step_from_row(row) for row in steps]

    def get_history(self, workflow_id: UUID) -> list[WorkflowHistoryEvent]:
        with transaction(self.settings) as connection:
            rows = connection.execute(
                """
                SELECT * FROM workflow_events
                WHERE workflow_id = %s ORDER BY created_at, id
                """,
                (workflow_id,),
            ).fetchall()
            return [_event_from_row(row) for row in rows]

    def get_status_summary(self, workflow_id: UUID) -> dict[str, Any] | None:
        state = self.get_workflow(workflow_id)
        if state is None:
            return None
        workflow, steps = state
        return {
            "workflow_id": workflow.id,
            "status": workflow.status,
            "definition_name": workflow.definition_name,
            "steps": [
                {"name": step.step_name, "status": step.status, "attempts": step.attempt_count}
                for step in steps
            ],
        }

    def create_or_get_payment_effect(
        self,
        idempotency_key: str,
        workflow_id: UUID,
        amount_cents: int,
        currency: str,
    ) -> dict[str, Any]:
        """Persist one payment effect in its own transaction and return its result."""
        with transaction(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO payment_effects
                    (id, idempotency_key, workflow_id, amount_cents, currency,
                     status, provider_reference)
                VALUES (%s, %s, %s, %s, %s, 'succeeded', %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    uuid4(),
                    idempotency_key,
                    workflow_id,
                    amount_cents,
                    currency,
                    f"pay_{uuid4().hex}",
                ),
            )
            row = connection.execute(
                """
                SELECT idempotency_key, provider_reference, amount_cents, currency, status
                FROM payment_effects WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise RepositoryError("payment effect was not persisted")
            return {
                "idempotency_key": row["idempotency_key"],
                "provider_reference": row["provider_reference"],
                "amount_cents": row["amount_cents"],
                "currency": row["currency"],
                "status": row["status"],
            }

    def claim_next_runnable_step(
        self, worker_id: str, lease_duration: timedelta
    ) -> ClaimedStep | None:
        with transaction(self.settings) as connection:
            row = connection.execute(
                """
                SELECT s.*
                FROM workflow_steps AS s
                JOIN workflows AS w ON w.id = s.workflow_id
                WHERE w.status = 'running'
                  AND s.status IN ('pending', 'retry_wait')
                  AND s.available_at <= NOW()
                  AND NOT EXISTS (
                      SELECT 1 FROM workflow_steps AS previous
                      WHERE previous.workflow_id = s.workflow_id
                        AND previous.step_order < s.step_order
                        AND previous.status <> 'succeeded'
                  )
                ORDER BY s.created_at, s.step_order
                FOR UPDATE OF s SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            attempt_number = row["attempt_count"] + 1
            updated = connection.execute(
                """
                UPDATE workflow_steps
                SET status = 'running', attempt_count = %s, lease_owner = %s,
                    lease_expires_at = NOW() + %s::interval,
                    started_at = COALESCE(started_at, NOW()),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (attempt_number, worker_id, f"{lease_duration.total_seconds()} seconds", row["id"]),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO step_attempts (workflow_step_id, attempt_number, worker_id, status)
                VALUES (%s, %s, %s, 'running')
                """,
                (row["id"], attempt_number, worker_id),
            )
            connection.execute(
                """
                INSERT INTO workflow_events (workflow_id, workflow_step_id, event_type, details)
                VALUES (%s, %s, 'step_claimed', %s)
                """,
                (
                    row["workflow_id"],
                    row["id"],
                    Jsonb({"worker_id": worker_id, "attempt_number": attempt_number}),
                ),
            )
            return ClaimedStep(_step_from_row(updated), attempt_number, worker_id)

    def recover_expired_leases(self) -> int:
        """Make expired running steps immediately eligible, transactionally."""
        recovered = 0
        with transaction(self.settings) as connection:
            rows = connection.execute(
                """
                SELECT * FROM workflow_steps
                WHERE status = 'running' AND lease_expires_at <= NOW()
                FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            for row in rows:
                error = {
                    "type": "lease_expired",
                    "message": "worker lease expired before completion was recorded",
                    "worker_id": row["lease_owner"],
                    "attempt_number": row["attempt_count"],
                }
                connection.execute(
                    """
                    UPDATE step_attempts SET status = 'failed', error = %s, completed_at = NOW()
                    WHERE workflow_step_id = %s AND attempt_number = %s
                    """,
                    (Jsonb(error), row["id"], row["attempt_count"]),
                )
                self._event(connection, row["workflow_id"], row["id"], "step_lease_expired", error)
                if row["attempt_count"] < row["max_attempts"]:
                    connection.execute(
                        """
                        UPDATE workflow_steps
                        SET status = 'retry_wait', lease_owner = NULL, lease_expires_at = NULL,
                            available_at = NOW(), last_error = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (Jsonb(error), row["id"]),
                    )
                    self._event(
                        connection,
                        row["workflow_id"],
                        row["id"],
                        "step_retry_scheduled",
                        {**error, "available_at": "now"},
                    )
                else:
                    connection.execute(
                        """
                        UPDATE workflow_steps SET status = 'failed', lease_owner = NULL,
                            lease_expires_at = NULL, last_error = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (Jsonb(error), row["id"]),
                    )
                    connection.execute(
                        "UPDATE workflows SET status = 'failed', updated_at = NOW() WHERE id = %s",
                        (row["workflow_id"],),
                    )
                    self._event(connection, row["workflow_id"], row["id"], "step_failed", error)
                    self._event(connection, row["workflow_id"], None, "workflow_failed", error)
                recovered += 1
        return recovered

    def mark_step_succeeded(self, step_id: UUID, worker_id: str, output: dict[str, Any]) -> None:
        with transaction(self.settings) as connection:
            row = self._lock_owned_step(connection, step_id, worker_id)
            connection.execute(
                """
                UPDATE workflow_steps SET status = 'succeeded', output = %s,
                    lease_owner = NULL, lease_expires_at = NULL,
                    completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                """,
                (Jsonb(output), step_id),
            )
            connection.execute(
                """UPDATE step_attempts SET status = 'succeeded', completed_at = NOW()
                   WHERE workflow_step_id = %s AND attempt_number = %s""",
                (step_id, row["attempt_count"]),
            )
            self._event(
                connection,
                row["workflow_id"],
                step_id,
                "step_succeeded",
                {"attempt_number": row["attempt_count"]},
            )
            remaining = connection.execute(
                """SELECT 1 FROM workflow_steps
                   WHERE workflow_id = %s AND status <> 'succeeded' LIMIT 1""",
                (row["workflow_id"],),
            ).fetchone()
            if remaining is None:
                connection.execute(
                    """UPDATE workflows SET status = 'succeeded', completed_at = NOW(),
                       updated_at = NOW() WHERE id = %s""",
                    (row["workflow_id"],),
                )
                self._event(connection, row["workflow_id"], None, "workflow_succeeded", {})

    def schedule_step_retry(
        self, step_id: UUID, worker_id: str, error: dict[str, Any], available_at: datetime
    ) -> None:
        self._finish_step(
            step_id, worker_id, "retry_wait", error, available_at, "step_retry_scheduled"
        )

    def mark_step_failed(self, step_id: UUID, worker_id: str, error: dict[str, Any]) -> None:
        with transaction(self.settings) as connection:
            row = self._lock_owned_step(connection, step_id, worker_id)
            connection.execute(
                """UPDATE workflow_steps SET status = 'failed', last_error = %s,
                   lease_owner = NULL, lease_expires_at = NULL, updated_at = NOW() WHERE id = %s""",
                (Jsonb(error), step_id),
            )
            connection.execute(
                """UPDATE step_attempts SET status = 'failed', error = %s, completed_at = NOW()
                   WHERE workflow_step_id = %s AND attempt_number = %s""",
                (Jsonb(error), step_id, row["attempt_count"]),
            )
            self._event(connection, row["workflow_id"], step_id, "step_failed", error)
            connection.execute(
                "UPDATE workflows SET status = 'failed', updated_at = NOW() WHERE id = %s",
                (row["workflow_id"],),
            )
            self._event(connection, row["workflow_id"], None, "workflow_failed", error)

    def _finish_step(
        self,
        step_id: UUID,
        worker_id: str,
        status: str,
        error: dict[str, Any],
        available_at: datetime,
        event: str,
    ) -> None:
        with transaction(self.settings) as connection:
            row = self._lock_owned_step(connection, step_id, worker_id)
            connection.execute(
                """UPDATE workflow_steps SET status = %s, last_error = %s, available_at = %s,
                   lease_owner = NULL, lease_expires_at = NULL, updated_at = NOW() WHERE id = %s""",
                (status, Jsonb(error), available_at, step_id),
            )
            connection.execute(
                """UPDATE step_attempts SET status = 'failed', error = %s, completed_at = NOW()
                   WHERE workflow_step_id = %s AND attempt_number = %s""",
                (Jsonb(error), step_id, row["attempt_count"]),
            )
            self._event(
                connection,
                row["workflow_id"],
                step_id,
                event,
                {"error": error, "available_at": available_at.isoformat()},
            )

    @staticmethod
    def _lock_owned_step(
        connection: psycopg.Connection, step_id: UUID, worker_id: str
    ) -> dict[str, Any]:
        row = connection.execute(
            """SELECT * FROM workflow_steps WHERE id = %s AND status = 'running'
               AND lease_owner = %s AND lease_expires_at > NOW() FOR UPDATE""",
            (step_id, worker_id),
        ).fetchone()
        if row is None:
            raise LeaseLostError(
                f"worker {worker_id} does not own an active lease for step {step_id}"
            )
        return row

    @staticmethod
    def _event(
        connection: psycopg.Connection,
        workflow_id: UUID,
        step_id: UUID | None,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO workflow_events
               (workflow_id, workflow_step_id, event_type, details)
               VALUES (%s, %s, %s, %s)""",
            (workflow_id, step_id, event_type, Jsonb(details)),
        )


def _workflow_from_row(row: dict[str, Any]) -> PersistedWorkflowSummary:
    return PersistedWorkflowSummary(
        row["id"],
        row["definition_name"],
        row["definition_version"],
        row["idempotency_key"],
        WorkflowStatus(row["status"]),
        row["input"],
        row["output"],
        row["created_at"],
        row["updated_at"],
        row["completed_at"],
    )


def _step_from_row(row: dict[str, Any]) -> PersistedWorkflowStep:
    return PersistedWorkflowStep(
        row["id"],
        row["workflow_id"],
        row["step_name"],
        row["step_order"],
        StepStatus(row["status"]),
        row["attempt_count"],
        row["max_attempts"],
        row["available_at"],
        row["lease_owner"],
        row["lease_expires_at"],
        row["input"],
        row["output"],
        row["last_error"],
        row["created_at"],
        row["updated_at"],
        row["started_at"],
        row["completed_at"],
    )


def _event_from_row(row: dict[str, Any]) -> WorkflowHistoryEvent:
    return WorkflowHistoryEvent(
        row["id"],
        row["workflow_id"],
        row["workflow_step_id"],
        row["event_type"],
        row["details"],
        row["created_at"],
    )

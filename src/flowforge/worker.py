"""Single-process workflow worker."""

import logging
import os
import time
from datetime import timedelta
from uuid import UUID, uuid4

from .activities.inventory import reserve_inventory
from .activities.payments import charge_payment
from .activities.receipts import send_receipt
from .repository import WorkflowRepository
from .retry import (
    NonRetryableActivityError,
    RetryableActivityError,
    error_details,
    retry_delay,
)

LOGGER = logging.getLogger(__name__)
LEASE_DURATION = timedelta(seconds=30)


def crash_after_effect_step(step_name: str) -> bool:
    """Return whether the opt-in crash hook targets this step."""
    return os.getenv("FLOWFORGE_CRASH_AFTER_EFFECT") == step_name


class Worker:
    def __init__(
        self, repository: WorkflowRepository | None = None, worker_id: str | None = None
    ) -> None:
        self.repository = repository or WorkflowRepository()
        self.worker_id = worker_id or f"worker-{uuid4().hex[:12]}"

    def run_once(self) -> bool:
        self.repository.recover_expired_leases()
        claimed = self.repository.claim_next_runnable_step(self.worker_id, LEASE_DURATION)
        if claimed is None:
            return False
        workflow_state = self.repository.get_workflow(claimed.step.workflow_id)
        if workflow_state is None:
            raise RuntimeError(f"workflow not found: {claimed.step.workflow_id}")
        workflow, _ = workflow_state
        payload = workflow.input
        LOGGER.info("step claimed workflow_id=%s step=%s", workflow.id, claimed.step.step_name)
        try:
            output = self._invoke(claimed.step.step_name, claimed.step.workflow_id, payload)
            if crash_after_effect_step(claimed.step.step_name):
                os._exit(137)
            self.repository.mark_step_succeeded(claimed.step.id, self.worker_id, output)
            LOGGER.info(
                "step succeeded workflow_id=%s step=%s", workflow.id, claimed.step.step_name
            )
        except RetryableActivityError as exc:
            error = error_details(exc)
            if claimed.attempt_number < claimed.step.max_attempts:
                from datetime import datetime, timezone

                available_at = datetime.now(timezone.utc) + retry_delay(claimed.attempt_number)
                self.repository.schedule_step_retry(
                    claimed.step.id, self.worker_id, error, available_at
                )
                LOGGER.warning(
                    "step retry scheduled workflow_id=%s step=%s attempt=%s",
                    workflow.id,
                    claimed.step.step_name,
                    claimed.attempt_number,
                )
            else:
                self.repository.mark_step_failed(claimed.step.id, self.worker_id, error)
        except (NonRetryableActivityError, Exception) as exc:
            error = error_details(exc)
            self.repository.mark_step_failed(claimed.step.id, self.worker_id, error)
            LOGGER.exception(
                "step failed workflow_id=%s step=%s", workflow.id, claimed.step.step_name
            )
        return True

    def run_until_idle(self, max_steps: int | None = None) -> int:
        processed = 0
        while max_steps is None or processed < max_steps:
            self.repository.recover_expired_leases()
            if not self.run_once():
                break
            processed += 1
        return processed

    def run_polling(self, poll_interval: float = 1.0) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        while True:
            if not self.run_once():
                time.sleep(poll_interval)

    def _invoke(
        self, step_name: str, workflow_id: UUID, payload: dict[str, object]
    ) -> dict[str, object]:
        if step_name == "reserve_inventory":
            return reserve_inventory(workflow_id, payload)
        if step_name == "charge_payment":
            return charge_payment(workflow_id, payload, self.repository)
        if step_name == "send_receipt":
            return send_receipt(workflow_id, payload)
        raise ValueError(f"unknown workflow step: {step_name}")

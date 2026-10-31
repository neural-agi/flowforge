"""Payment activity backed by the local payment-effects provider."""

from typing import Any
from uuid import UUID

from ..repository import WorkflowRepository


def payment_idempotency_key(workflow_id: UUID) -> str:
    return f"{workflow_id}:charge_payment"


def charge_payment(
    workflow_id: UUID, payload: dict[str, Any], repository: WorkflowRepository
) -> dict[str, Any]:
    key = payment_idempotency_key(workflow_id)
    effect = repository.create_or_get_payment_effect(
        key, workflow_id, payload["amount_cents"], payload["currency"]
    )
    return effect

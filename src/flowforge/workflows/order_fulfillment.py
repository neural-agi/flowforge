"""The fixed sequential order-fulfillment workflow."""

from dataclasses import dataclass
from typing import Any, Callable

from ..models import StepSpecification

ORDER_FULFILLMENT = "order_fulfillment"
VERSION = "1"
STEP_NAMES = ("reserve_inventory", "charge_payment", "send_receipt")
Activity = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    version: str
    steps: tuple[str, ...]

    def specifications(self, workflow_input: dict[str, Any]) -> tuple[StepSpecification, ...]:
        return tuple(
            StepSpecification(name, index, input=workflow_input)
            for index, name in enumerate(self.steps, start=1)
        )


DEFINITION = WorkflowDefinition(ORDER_FULFILLMENT, VERSION, STEP_NAMES)


def validate_input(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("workflow input must be a JSON object")
    required = {
        "order_id": str,
        "sku": str,
        "quantity": int,
        "amount_cents": int,
        "currency": str,
        "customer_email": str,
    }
    for field, expected_type in required.items():
        if field not in value or not isinstance(value[field], expected_type):
            raise ValueError(f"workflow input field '{field}' must be a {expected_type.__name__}")
    if value["quantity"] <= 0 or value["amount_cents"] <= 0:
        raise ValueError("quantity and amount_cents must be positive")
    return value


def get_workflow_definition(name: str) -> WorkflowDefinition:
    if name != ORDER_FULFILLMENT:
        raise ValueError(f"unknown workflow: {name}")
    return DEFINITION

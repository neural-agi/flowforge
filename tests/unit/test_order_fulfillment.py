import json
from uuid import UUID, uuid4

import pytest

from flowforge.activities.inventory import reserve_inventory
from flowforge.activities.payments import payment_idempotency_key
from flowforge.activities.receipts import send_receipt
from flowforge.workflows.order_fulfillment import (
    ORDER_FULFILLMENT,
    get_workflow_definition,
    validate_input,
)

PAYLOAD = {
    "order_id": "order-1001",
    "sku": "demo-widget",
    "quantity": 1,
    "amount_cents": 1999,
    "currency": "USD",
    "customer_email": "customer@example.com",
}


def test_valid_and_invalid_workflow_input() -> None:
    assert validate_input(json.loads(json.dumps(PAYLOAD))) == PAYLOAD
    with pytest.raises(ValueError, match="customer_email"):
        validate_input({**PAYLOAD, "customer_email": 42})


def test_registry_resolves_fixed_workflow() -> None:
    definition = get_workflow_definition(ORDER_FULFILLMENT)
    assert definition.steps == ("reserve_inventory", "charge_payment", "send_receipt")
    with pytest.raises(ValueError, match="unknown"):
        get_workflow_definition("other")


def test_activity_results_are_deterministic() -> None:
    workflow_id = UUID("00000000-0000-0000-0000-000000000001")
    assert reserve_inventory(workflow_id, PAYLOAD) == reserve_inventory(workflow_id, PAYLOAD)
    assert send_receipt(workflow_id, PAYLOAD) == send_receipt(workflow_id, PAYLOAD)


def test_payment_key_is_deterministic() -> None:
    workflow_id = uuid4()
    assert payment_idempotency_key(workflow_id) == f"{workflow_id}:charge_payment"

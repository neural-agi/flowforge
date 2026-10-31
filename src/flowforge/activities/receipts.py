"""Local receipt activity."""

from typing import Any
from uuid import UUID, uuid5


def send_receipt(workflow_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": payload["order_id"],
        "customer_email": payload["customer_email"],
        "receipt_reference": f"receipt_{uuid5(workflow_id, 'send_receipt').hex}",
    }

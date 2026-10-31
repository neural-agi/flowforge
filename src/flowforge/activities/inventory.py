"""Local inventory activity."""

from typing import Any
from uuid import UUID, uuid5


def reserve_inventory(workflow_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": payload["order_id"],
        "sku": payload["sku"],
        "quantity": payload["quantity"],
        "reservation_reference": f"reservation_{uuid5(workflow_id, 'reserve_inventory').hex}",
    }

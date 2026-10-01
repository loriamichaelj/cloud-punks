"""The request fingerprint behind idempotency.

Same ``Idempotency-Key`` with the same body returns the original order; the same key with a
different body is an error. "Same body" must not depend on how the client ordered its items.
"""

import hashlib
import json
from collections.abc import Sequence

from app.domain.models import OrderLine


def request_hash(customer_id: str, lines: Sequence[OrderLine]) -> str:
    """SHA-256 (64 hex chars) of the canonical request: customer plus items sorted by SKU."""
    canonical = {
        "customer_id": customer_id,
        "items": [
            {"sku": line.sku, "quantity": line.quantity}
            for line in sorted(lines, key=lambda line: line.sku)
        ],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

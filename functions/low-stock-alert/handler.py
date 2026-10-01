"""low-stock-alert Lambda (DESIGN.md section 6).

Triggered directly by EventBridge for every ``InventoryReserved``. For each item whose
``remaining`` is below ``LOW_STOCK_THRESHOLD`` (default 5) it writes one structured log record in
CloudWatch Embedded Metric Format: the same line is the ``low_stock`` log entry and the
``LowStockDetected`` metric, so no extra API call is needed. Standard library only.

No idempotency is needed (the effect is a log line and a count). A malformed event is logged and
dropped, not raised: it can never succeed, and an asynchronous invoke would retry it for nothing.
"""

import json
import os
import time
from typing import Any

DEFAULT_THRESHOLD = 5
NAMESPACE = "RetailPlatform"
SERVICE = "low-stock-alert"


def _threshold() -> int:
    try:
        return int(os.environ.get("LOW_STOCK_THRESHOLD", DEFAULT_THRESHOLD))
    except ValueError:
        return DEFAULT_THRESHOLD


def _emit(record: dict[str, Any]) -> None:
    print(json.dumps(record, separators=(",", ":")))


def _low_stock_record(
    sku: str, remaining: int, threshold: int, order_id: str, correlation_id: str | None
) -> dict[str, Any]:
    return {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["Service"]],  # the SKU is a log property, not a dimension
                    "Metrics": [{"Name": "LowStockDetected", "Unit": "Count"}],
                }
            ],
        },
        "Service": SERVICE,
        "LowStockDetected": 1,
        "level": "warning",
        "event": "low_stock",
        "sku": sku,
        "remaining": remaining,
        "threshold": threshold,
        "order_id": order_id,
        "correlation_id": correlation_id,
    }


def _stock_line(item: object) -> tuple[str, int] | None:
    """``(sku, remaining)`` for a well-formed item, else None."""
    if not isinstance(item, dict):
        return None
    sku, remaining = item.get("sku"), item.get("remaining")
    if isinstance(sku, str) and isinstance(remaining, int) and not isinstance(remaining, bool):
        return sku, remaining
    return None


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, int]:
    detail = event.get("detail") if isinstance(event, dict) else None
    data = detail.get("data") if isinstance(detail, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(detail, dict) or not isinstance(data, dict) or not isinstance(items, list):
        _emit({"level": "error", "event": "malformed_event", "service": SERVICE})
        return {"low_stock": 0}

    threshold = _threshold()
    order_id = str(data.get("order_id", ""))
    correlation_id = detail.get("correlation_id")
    found = 0
    for item in items:
        line = _stock_line(item)
        if line and line[1] < threshold:
            _emit(_low_stock_record(line[0], line[1], threshold, order_id, correlation_id))
            found += 1
    return {"low_stock": found}

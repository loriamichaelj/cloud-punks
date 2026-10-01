"""DynamoDB adapter for ``ReservationStore`` (tables ``inventory_reservations`` and ``inventory``).

Reserving is ONE ``TransactWriteItems``: a ``Put`` of the reservation record guarded by
``attribute_not_exists(order_id)`` plus one stock ``Update`` per SKU guarded by
``attribute_exists(sku) AND available >= :q``. All succeed or none do (DESIGN.md section 5).

When the transaction is cancelled, ``CancellationReasons`` says why, and the three causes MUST
NOT be conflated (the classic oversell / double-fail bug):

* the *reservation record* condition failed -> the order was already processed: a duplicate;
* a *stock* condition failed -> not enough stock, or no such SKU: a FAILED outcome;
* a conflict or throttling -> nothing was decided: retry later.

DynamoDB reserved words matter in expressions: ``status`` is one and is aliased as ``#status``.
(``items`` and ``ttl`` are too, but are only used as attribute names, which is allowed.)
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from botocore.exceptions import ClientError

from app.domain.errors import StoreUnavailable
from app.domain.reservations import (
    FailedLine,
    Reservation,
    ReservedLine,
    ReserveResult,
)
from app.repo.dynamodb import INVENTORY_TABLE, store_errors

RESERVATIONS_TABLE = "inventory_reservations"
# At least 30 days (DESIGN.md section 5): it must outlive SQS retention and any archive replay,
# otherwise a replayed OrderCreated would reserve a second time.
RESERVATION_TTL = timedelta(days=35)

# Cancellation reasons that mean "nothing was decided, try again", not "the answer is no".
_TRANSIENT_REASONS = frozenset(
    {
        "TransactionConflict",
        "ThrottlingError",
        "ProvisionedThroughputExceeded",
        "InternalServerError",
    }
)

_log = structlog.get_logger("reservation_store")


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: int) -> dict[str, str]:
    return {"N": str(value)}


def _lines(items: Sequence[ReservedLine]) -> dict[str, Any]:
    return {"L": [{"M": {"sku": {"S": i.sku}, "quantity": _number(i.quantity)}} for i in items]}


def _failed_lines(items: Sequence[FailedLine]) -> dict[str, Any]:
    return {
        "L": [
            {
                "M": {
                    "sku": {"S": i.sku},
                    "requested": _number(i.requested),
                    "available": _number(i.available),
                }
            }
            for i in items
        ]
    }


def _record(
    order_id: str,
    status: str,
    items: Sequence[ReservedLine],
    event_id: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "order_id": {"S": order_id},
        "status": {"S": status},
        "items": _lines(items),
        "event_id": {"S": event_id},
        "created_at": {"S": _timestamp(created_at)},
        "ttl": _number(int((created_at + RESERVATION_TTL).timestamp())),
    }


def _parse(raw: Mapping[str, Any]) -> Reservation:
    failed = tuple(
        FailedLine(
            sku=m["M"]["sku"]["S"],
            requested=int(m["M"]["requested"]["N"]),
            available=int(m["M"]["available"]["N"]),
        )
        for m in raw.get("failed_items", {}).get("L", [])
    )
    remaining = (
        {sku: int(value["N"]) for sku, value in raw["remaining"]["M"].items()}
        if "remaining" in raw
        else None
    )
    return Reservation(
        order_id=raw["order_id"]["S"],
        status=raw["status"]["S"],
        items=tuple(
            ReservedLine(m["M"]["sku"]["S"], int(m["M"]["quantity"]["N"]))
            for m in raw["items"]["L"]
        ),
        event_id=raw["event_id"]["S"],
        created_at=datetime.fromisoformat(raw["created_at"]["S"]),
        reason=raw["reason"]["S"] if "reason" in raw else None,
        failed_items=failed,
        remaining=remaining,
    )


class DynamoReservationStore:
    def __init__(
        self,
        client: Any,
        inventory_table: str = INVENTORY_TABLE,
        reservations_table: str = RESERVATIONS_TABLE,
    ) -> None:
        self._client = client
        self._inventory = inventory_table
        self._reservations = reservations_table

    def reserve(
        self, order_id: str, items: Sequence[ReservedLine], event_id: str, created_at: datetime
    ) -> ReserveResult:
        transaction: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._reservations,
                    "Item": _record(order_id, "RESERVED", items, event_id, created_at),
                    "ConditionExpression": "attribute_not_exists(order_id)",
                }
            },
            *(
                {
                    "Update": {
                        "TableName": self._inventory,
                        "Key": {"sku": {"S": item.sku}},
                        "UpdateExpression": (
                            "SET available = available - :q, "
                            "reserved = if_not_exists(reserved, :zero) + :q, updated_at = :now"
                        ),
                        "ConditionExpression": "attribute_exists(sku) AND available >= :q",
                        "ExpressionAttributeValues": {
                            ":q": _number(item.quantity),
                            ":zero": _number(0),
                            ":now": {"S": _timestamp(created_at)},
                        },
                        # Returns the item as it was, so an unknown SKU (no item) can be told
                        # apart from a shortfall (an item with too little `available`).
                        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                    }
                }
                for item in items
            ),
        ]
        try:
            with store_errors():
                self._client.transact_write_items(TransactItems=transaction)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            return self._after_cancellation(exc, order_id, items, event_id, created_at)
        return ReserveResult(
            Reservation(order_id, "RESERVED", tuple(items), event_id, created_at), created=True
        )

    def _after_cancellation(
        self,
        exc: ClientError,
        order_id: str,
        items: Sequence[ReservedLine],
        event_id: str,
        created_at: datetime,
    ) -> ReserveResult:
        reasons: list[dict[str, Any]] = exc.response.get("CancellationReasons", [])
        codes = [reason.get("Code", "None") for reason in reasons]

        # Index 0 is the reservation record. If *its* condition failed, this order was already
        # processed, whatever else the transaction also complained about.
        if codes and codes[0] == "ConditionalCheckFailed":
            existing = self.get(order_id)
            if existing is None:  # pragma: no cover - a record whose condition failed exists
                raise RuntimeError("reservation conflict without a stored reservation")
            return ReserveResult(existing, created=False)

        if _TRANSIENT_REASONS & set(codes):
            _log.warning("reservation_transaction_retryable", codes=codes)
            raise StoreUnavailable from exc

        failed: list[FailedLine] = []
        unknown = False
        for item, reason in zip(items, reasons[1:], strict=False):
            if reason.get("Code") != "ConditionalCheckFailed":
                continue
            old = reason.get("Item")
            if old:
                failed.append(FailedLine(item.sku, item.quantity, int(old["available"]["N"])))
            else:
                failed.append(FailedLine(item.sku, item.quantity, 0))
                unknown = True
        if not failed:
            raise RuntimeError(f"unexpected transaction cancellation: {codes}") from exc

        record = _record(order_id, "FAILED", items, event_id, created_at) | {
            "reason": {"S": "UNKNOWN_SKU" if unknown else "OUT_OF_STOCK"},
            "failed_items": _failed_lines(failed),
        }
        try:
            with store_errors():
                self._client.put_item(
                    TableName=self._reservations,
                    Item=record,
                    ConditionExpression="attribute_not_exists(order_id)",
                )
        except ClientError as put_exc:
            if put_exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(order_id)  # another delivery recorded the outcome first
            if existing is None:  # pragma: no cover
                raise RuntimeError("reservation conflict without a stored reservation") from put_exc
            return ReserveResult(existing, created=False)
        return ReserveResult(_parse(record), created=True)

    def get(self, order_id: str) -> Reservation | None:
        with store_errors():
            response = self._client.get_item(
                TableName=self._reservations, Key={"order_id": {"S": order_id}}, ConsistentRead=True
            )
        raw = response.get("Item")
        return _parse(raw) if raw else None

    def store_remaining(self, order_id: str, remaining: Mapping[str, int]) -> Reservation:
        try:
            with store_errors():
                response = self._client.update_item(
                    TableName=self._reservations,
                    Key={"order_id": {"S": order_id}},
                    UpdateExpression="SET remaining = :remaining",
                    # Written once: a redelivery that races us must not overwrite what was emitted.
                    ConditionExpression=(
                        "attribute_exists(order_id) AND #status = :reserved "
                        "AND attribute_not_exists(remaining)"
                    ),
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":remaining": {
                            "M": {sku: _number(left) for sku, left in remaining.items()}
                        },
                        ":reserved": {"S": "RESERVED"},
                    },
                    ReturnValues="ALL_NEW",
                )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(order_id)
            if existing is None:  # pragma: no cover
                raise RuntimeError("reservation vanished while storing remaining stock") from exc
            return existing
        return _parse(response["Attributes"])

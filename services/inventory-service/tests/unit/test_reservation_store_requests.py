"""The exact DynamoDB requests the reservation store sends, and how it reads every way a
transaction can be cancelled (DESIGN.md section 5, "Gotcha"), pinned with botocore's Stubber."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from botocore.stub import ANY, Stubber

from app.domain.errors import StoreUnavailable
from app.domain.reservations import ReservedLine
from app.repo.reservations import RESERVATION_TTL, DynamoReservationStore

ORDER = "01J9Z6Q4W8K3M2N1P0R7S5T4V3"
EVENT = "01J9Z6R0C4D5E6F7G8H9J0K1M2"
CREATED = datetime(2026, 10, 1, 12, 0, 0, 123000, tzinfo=UTC)
STAMP = "2026-10-01T12:00:00.123Z"
TTL = int((CREATED + timedelta(days=35)).timestamp())
ITEMS = [ReservedLine("A", 2), ReservedLine("B", 1)]
BUYER = "cust-buyer"
SELLER = "cust-seller"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")


@pytest.fixture
def stub() -> Any:
    client = boto3.client("dynamodb", region_name="us-east-1")
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def reservation_item(status: str = "RESERVED", **extra: Any) -> dict[str, Any]:
    return {
        "order_id": {"S": ORDER},
        "status": {"S": status},
        "items": {"L": [{"M": {"sku": {"S": "A"}, "quantity": {"N": "2"}}}, {"M": {"sku": {"S": "B"}, "quantity": {"N": "1"}}}]},
        "event_id": {"S": EVENT},
        "created_at": {"S": STAMP},
        "ttl": {"N": str(TTL)},
        "buyer": {"S": BUYER},
        **extra,
    }  # fmt: skip


def stock_update(sku: str, quantity: int) -> dict[str, Any]:
    """A purchase from the platform: the stock decides, and the buyer becomes the owner."""
    return {
        "Update": {
            "TableName": "inventory",
            "Key": {"sku": {"S": sku}},
            "UpdateExpression": "SET available = available - :q, reserved = if_not_exists(reserved, :zero) + :q, updated_at = :now, #owner = :buyer",
            "ConditionExpression": "attribute_exists(sku) AND available >= :q",
            "ExpressionAttributeNames": {"#owner": "owner"},
            "ExpressionAttributeValues": {":q": {"N": str(quantity)}, ":zero": {"N": "0"}, ":now": {"S": STAMP}, ":buyer": {"S": BUYER}},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        }
    }  # fmt: skip


def resale_update(sku: str) -> dict[str, Any]:
    """A resale: the seller must still own it; ownership moves, the stock is not touched."""
    return {
        "Update": {
            "TableName": "inventory",
            "Key": {"sku": {"S": sku}},
            "UpdateExpression": "SET reserved = if_not_exists(reserved, :zero) + :q, updated_at = :now, #owner = :buyer",
            "ConditionExpression": "attribute_exists(sku) AND #owner = :seller",
            "ExpressionAttributeNames": {"#owner": "owner"},
            "ExpressionAttributeValues": {":q": {"N": "1"}, ":zero": {"N": "0"}, ":now": {"S": STAMP}, ":buyer": {"S": BUYER}, ":seller": {"S": SELLER}},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        }
    }  # fmt: skip


RESALE = [ReservedLine("CP-0001", 1)]
EXPECTED_RESALE = {
    "TransactItems": [
        {
            "Put": {
                "TableName": "inventory_reservations",
                "Item": {
                    **reservation_item(),
                    "items": {"L": [{"M": {"sku": {"S": "CP-0001"}, "quantity": {"N": "1"}}}]},
                    "seller": {"S": SELLER},
                },
                "ConditionExpression": "attribute_not_exists(order_id)",
            }
        },
        resale_update("CP-0001"),
    ]
}


EXPECTED_TRANSACTION = {
    "TransactItems": [
        {
            "Put": {
                "TableName": "inventory_reservations",
                "Item": reservation_item(),
                "ConditionExpression": "attribute_not_exists(order_id)",
            }
        },
        stock_update("A", 2),
        stock_update("B", 1),
    ]
}


def cancelled(stubber: Any, reasons: list[dict[str, Any]], **kwargs: Any) -> None:
    stubber.add_client_error(
        "transact_write_items",
        service_error_code="TransactionCanceledException",
        service_message="Transaction cancelled, please refer cancellation reasons for specific reasons",
        http_status_code=400,
        modeled_fields={"CancellationReasons": reasons},
        **kwargs,
    )


NONE = {"Code": "None"}
CCF = {"Code": "ConditionalCheckFailed", "Message": "The conditional request failed"}


def with_item(available: int, owner: str | None = None) -> dict[str, Any]:
    item = {"sku": {"S": "x"}, "available": {"N": str(available)}, "reserved": {"N": "0"}}
    if owner is not None:
        item["owner"] = {"S": owner}
    return {**CCF, "Item": item}


def store(client: Any) -> DynamoReservationStore:
    return DynamoReservationStore(client)


# --- the happy path: one transaction, exactly as designed -----------------------------------


def test_reserving_is_one_transaction_with_a_guarded_put_and_one_guarded_update_per_sku(
    stub: Any,
) -> None:
    client, stubber = stub
    stubber.add_response("transact_write_items", {}, expected_params=EXPECTED_TRANSACTION)

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.created is True
    assert result.reservation.status == "RESERVED"
    assert result.reservation.event_id == EVENT
    assert (result.reservation.buyer, result.reservation.seller) == (BUYER, None)


def test_a_resale_is_guarded_by_the_seller_still_owning_it_and_leaves_stock_alone(
    stub: Any,
) -> None:
    client, stubber = stub
    stubber.add_response("transact_write_items", {}, expected_params=EXPECTED_RESALE)

    result = store(client).reserve(ORDER, RESALE, EVENT, CREATED, buyer=BUYER, seller=SELLER)

    assert result.reservation.status == "RESERVED"
    assert (result.reservation.buyer, result.reservation.seller) == (BUYER, SELLER)


def test_every_stock_update_asks_for_the_old_item_back_on_failure(stub: Any) -> None:
    """Without ALL_OLD an unknown SKU cannot be told apart from a shortfall or a new owner."""
    updates = [i["Update"] for i in EXPECTED_TRANSACTION["TransactItems"][1:]]
    resale = EXPECTED_RESALE["TransactItems"][1]["Update"]
    for u in [*updates, resale]:
        assert u["ReturnValuesOnConditionCheckFailure"] == "ALL_OLD"
        assert "attribute_exists(sku)" in u["ConditionExpression"]
        assert u["UpdateExpression"].endswith("#owner = :buyer")  # the transfer
    assert all("available >= :q" in u["ConditionExpression"] for u in updates)
    assert "#owner = :seller" in resale["ConditionExpression"]
    assert "available" not in resale["UpdateExpression"]


def test_the_reservation_outlives_sqs_retention_and_any_archive_replay() -> None:
    assert timedelta(days=30) <= RESERVATION_TTL
    assert reservation_item()["ttl"] == {"N": str(int((CREATED + RESERVATION_TTL).timestamp()))}


# --- cancellation: three different causes, three different outcomes ---------------------------


def test_a_conflict_on_the_reservation_record_means_duplicate_and_returns_the_stored_one(
    stub: Any,
) -> None:
    client, stubber = stub
    cancelled(stubber, [CCF, NONE, NONE])  # the request shape is pinned by the happy-path test
    stubber.add_response(
        "get_item",
        {"Item": reservation_item(remaining={"M": {"A": {"N": "8"}, "B": {"N": "3"}}})},
        expected_params={"TableName": "inventory_reservations", "Key": {"order_id": {"S": ORDER}}, "ConsistentRead": True},
    )  # fmt: skip

    result = store(client).reserve(ORDER, ITEMS, "01NEWEVENTIDNEWEVENTID01", CREATED, buyer=BUYER)

    assert result.created is False
    assert result.reservation.event_id == EVENT  # the ORIGINAL outcome event, not the new id
    assert result.reservation.remaining == {"A": 8, "B": 3}


def test_a_duplicate_wins_even_if_a_stock_line_also_failed(stub: Any) -> None:
    """Re-delivery after the stock has since run out must still be a duplicate, not a failure."""
    client, stubber = stub
    cancelled(stubber, [CCF, with_item(0), NONE])
    stubber.add_response("get_item", {"Item": reservation_item()})

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.created is False
    assert result.reservation.status == "RESERVED"


def test_a_shortfall_records_a_failed_outcome_with_the_available_quantities(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, with_item(1), NONE])
    stubber.add_response(
        "put_item",
        {},
        expected_params={
            "TableName": "inventory_reservations",
            "Item": {
                **reservation_item("FAILED"),
                "reason": {"S": "OUT_OF_STOCK"},
                "failed_items": {"L": [{"M": {"sku": {"S": "A"}, "requested": {"N": "2"}, "available": {"N": "1"}}}]},
            },
            "ConditionExpression": "attribute_not_exists(order_id)",
        },
    )  # fmt: skip

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.created is True
    assert result.reservation.status == "FAILED"
    assert result.reservation.reason == "OUT_OF_STOCK"
    assert [(f.sku, f.requested, f.available) for f in result.reservation.failed_items] == [
        ("A", 2, 1)
    ]


def test_a_cloudpunk_someone_owns_fails_as_sold(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, with_item(0, owner="cust-earlier"), NONE])
    stubber.add_response(
        "put_item",
        {},
        expected_params={
            "TableName": "inventory_reservations",
            "Item": {
                **reservation_item("FAILED"),
                "reason": {"S": "OUT_OF_STOCK"},
                "failed_items": {"L": [{"M": {"sku": {"S": "A"}, "requested": {"N": "2"}, "available": {"N": "0"}}}]},
                "detail": {"S": "SOLD"},
            },
            "ConditionExpression": "attribute_not_exists(order_id)",
        },
    )  # fmt: skip

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert (result.reservation.reason, result.reservation.detail) == ("OUT_OF_STOCK", "SOLD")


def test_a_resale_whose_seller_no_longer_owns_it_fails_as_owner_changed(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, with_item(0, owner="cust-someone-else")])
    stubber.add_response("put_item", {}, expected_params=ANY_PUT)

    result = store(client).reserve(ORDER, RESALE, EVENT, CREATED, buyer=BUYER, seller=SELLER)

    assert (result.reservation.reason, result.reservation.detail) == (
        "OUT_OF_STOCK",
        "OWNER_CHANGED",
    )
    assert result.reservation.seller == SELLER


def test_a_plain_shortfall_in_counted_stock_has_no_detail(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, with_item(1), NONE])
    stubber.add_response("put_item", {}, expected_params=ANY_PUT)

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.reservation.detail is None


def test_a_stock_line_with_no_item_is_an_unknown_sku(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, NONE, CCF])  # B failed and returned no Item: it does not exist
    stubber.add_response("put_item", {}, expected_params=ANY_PUT)

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.reservation.reason == "UNKNOWN_SKU"
    assert [(f.sku, f.available) for f in result.reservation.failed_items] == [("B", 0)]


def test_unknown_sku_takes_precedence_and_every_failing_line_is_listed(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, with_item(1), CCF])
    stubber.add_response("put_item", {}, expected_params=ANY_PUT)

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.reservation.reason == "UNKNOWN_SKU"
    assert [(f.sku, f.available) for f in result.reservation.failed_items] == [("A", 1), ("B", 0)]


ANY_PUT = {
    "TableName": "inventory_reservations",
    "Item": ANY,
    "ConditionExpression": "attribute_not_exists(order_id)",
}


def test_losing_the_race_to_record_the_failure_returns_the_other_deliverys_record(
    stub: Any,
) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, with_item(1), NONE])
    stubber.add_client_error("put_item", service_error_code="ConditionalCheckFailedException")
    stubber.add_response(
        "get_item", {"Item": reservation_item("FAILED", reason={"S": "OUT_OF_STOCK"})}
    )

    result = store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)

    assert result.created is False
    assert result.reservation.status == "FAILED"


@pytest.mark.parametrize(
    "code",
    [
        "TransactionConflict",
        "ThrottlingError",
        "ProvisionedThroughputExceeded",
        "InternalServerError",
    ],
)
def test_conflicts_and_throttling_decide_nothing_so_they_are_retried(stub: Any, code: str) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, {"Code": code}, NONE])  # no put_item / get_item may follow

    with pytest.raises(StoreUnavailable):
        store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)


def test_a_cancellation_nobody_understands_is_an_error_not_a_guess(stub: Any) -> None:
    client, stubber = stub
    cancelled(stubber, [NONE, {"Code": "ValidationError"}, NONE])
    with pytest.raises(RuntimeError, match="unexpected transaction cancellation"):
        store(client).reserve(ORDER, ITEMS, EVENT, CREATED, buyer=BUYER)


# --- remaining stock, written once ------------------------------------------------------------


def test_remaining_is_stored_once_with_the_reserved_word_aliased(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response(
        "update_item",
        {"Attributes": reservation_item(remaining={"M": {"A": {"N": "8"}}})},
        expected_params={
            "TableName": "inventory_reservations",
            "Key": {"order_id": {"S": ORDER}},
            "UpdateExpression": "SET remaining = :remaining",
            "ConditionExpression": "attribute_exists(order_id) AND #status = :reserved AND attribute_not_exists(remaining)",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":remaining": {"M": {"A": {"N": "8"}}}, ":reserved": {"S": "RESERVED"}},
            "ReturnValues": "ALL_NEW",
        },
    )  # fmt: skip

    assert store(client).store_remaining(ORDER, {"A": 8}).remaining == {"A": 8}


def test_if_remaining_was_already_stored_the_existing_record_wins(stub: Any) -> None:
    client, stubber = stub
    stubber.add_client_error("update_item", service_error_code="ConditionalCheckFailedException")
    stubber.add_response("get_item", {"Item": reservation_item(remaining={"M": {"A": {"N": "5"}}})})

    assert store(client).store_remaining(ORDER, {"A": 8}).remaining == {"A": 5}  # not overwritten


def test_a_missing_record_reads_as_none(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response("get_item", {})
    assert store(client).get(ORDER) is None


# --- DynamoDB reserved words ------------------------------------------------------------------

# From the AWS reserved-words list, the ones our attribute names collide with. LocalStack accepts
# them in places real DynamoDB rejects, so this is checked statically on every expression we build.
RESERVED_AMONG_OUR_ATTRIBUTES = {"status", "items", "ttl", "owner"}
KEYWORDS = {"set", "and", "or", "not", "attribute_exists", "attribute_not_exists", "if_not_exists"}


def expressions(request: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for item in request.get("TransactItems", [request]):
        body = (
            next(iter(item.values()))
            if len(item) == 1 and isinstance(next(iter(item.values())), dict)
            else item
        )
        found += [body[k] for k in ("UpdateExpression", "ConditionExpression") if k in body]
    return found


def test_no_expression_uses_a_reserved_word_unaliased(stub: Any) -> None:
    update_item_request = {
        "UpdateExpression": "SET remaining = :remaining",
        "ConditionExpression": "attribute_exists(order_id) AND #status = :reserved AND attribute_not_exists(remaining)",
    }
    texts = [
        *expressions(EXPECTED_TRANSACTION),
        *expressions(EXPECTED_RESALE),
        *expressions(update_item_request),
        ANY_PUT["ConditionExpression"],
    ]
    assert len(texts) >= 8

    for text in texts:
        names = {t.lower() for t in re.findall(r"(?<![:#\w])[A-Za-z_][A-Za-z_]*", text)} - KEYWORDS
        assert not names & RESERVED_AMONG_OUR_ATTRIBUTES, f"unaliased reserved word in: {text}"

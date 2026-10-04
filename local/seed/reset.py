"""Reset the CloudPunks market to a clean state: no orders, no listings, no bids, no activity, and
every CloudPunk back with the platform (red, unsold). Dev and local only; the catalog is untouched.

* order_db: every bid, listing, order (with its items) and outbox row is deleted in ONE transaction,
  children first. ``processed_events`` is kept on purpose: it is the consumers' dedupe, and a late
  redelivery of an old event must still be recognised as a duplicate. The activity feed is computed
  from these tables, so it empties with them.
* DynamoDB inventory: each CloudPunk's stock item is put back as the seed first wrote it
  (``available = 1``, ``reserved = 0``, no ``owner``). An unconditional put, because the cloud seed
  role may put items and nothing else. Reservation records stay: they are keyed by order id, and a
  new order always has a new ULID.
* Notifications are left: they are keyed by order id and read only by order id, so once the orders
  are gone nothing can show them (and no role may delete from that table).

Run it while nobody is buying: an event still in flight for a deleted order finds no order and is
skipped. Connection settings come from the environment only, as for ``seed.py`` (DB_* for order_db
as the app role, AWS_REGION, INVENTORY_TABLE). The "App: reset" workflow runs it for dev.
"""

import os
import sys
from datetime import UTC, datetime
from typing import Any

import boto3
import psycopg
import structlog
from catalog import STOCK
from psycopg.conninfo import make_conninfo

from retail_common.logging import configure_logging

_log = structlog.get_logger("reset")

ALLOWED_ENVIRONMENTS = frozenset({"local", "dev"})

# Children before parents: bids point at listings and orders, order_items at orders.
MARKET_TABLES: tuple[str, ...] = ("bids", "listings", "order_items", "orders", "outbox")


def reset_orders(conn: Any) -> dict[str, int]:
    """Delete the market's rows in one transaction; returns the count deleted per table."""
    deleted: dict[str, int] = {}
    with conn.transaction(), conn.cursor() as cur:
        for table in MARKET_TABLES:
            # Names from the constant above, never from input.
            cur.execute(f"DELETE FROM {table}")  # noqa: S608
            deleted[f"{table}_deleted"] = cur.rowcount
    return deleted


def reset_stock(dynamodb: Any, table: str = "inventory") -> dict[str, int]:
    """Put every CloudPunk's stock item back with the platform: one unit, nothing reserved."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for sku, quantity in STOCK.items():
        dynamodb.put_item(
            TableName=table,
            Item={
                "sku": {"S": sku},
                "available": {"N": str(quantity)},
                "reserved": {"N": "0"},
                "updated_at": {"S": now},
            },
        )
    return {"stock_reset": len(STOCK)}


def main() -> int:
    environment = os.environ.get("ENVIRONMENT", "local")
    configure_logging("reset", environment, "INFO")
    if environment not in ALLOWED_ENVIRONMENTS:
        _log.error("reset_refused", reason="local and dev only")
        return 2
    conninfo = make_conninfo(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.environ.get("DB_SSLMODE", "disable"),
    )
    # No endpoint or credentials here: boto3 reads AWS_ENDPOINT_URL and the default chain itself.
    dynamodb = boto3.client("dynamodb", region_name=os.environ["AWS_REGION"])

    with psycopg.connect(conninfo) as conn:
        orders = reset_orders(conn)
    stock = reset_stock(dynamodb, os.environ.get("INVENTORY_TABLE", "inventory"))
    _log.info("reset_complete", environment=environment, **orders, **stock)
    return 0


if __name__ == "__main__":
    sys.exit(main())

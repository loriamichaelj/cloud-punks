"""Seed the catalog (PostgreSQL product_db) and stock (DynamoDB inventory). Safe to re-run.

* Catalog rows use ``INSERT ... ON CONFLICT DO NOTHING``: existing rows are never modified.
* Stock uses a conditional put (``attribute_not_exists(sku)``): a re-seed never resets stock that
  orders have already drawn down.

Connection settings come from the environment only (DB_*, AWS_REGION, and boto3's own
AWS_ENDPOINT_URL / credential variables). Runs as the ``seed`` Compose service from the product
image (``make seed``).
"""

import os
import sys
from datetime import UTC, datetime
from typing import Any

import boto3
import psycopg
import structlog
from botocore.exceptions import ClientError
from catalog import CATEGORIES, PRODUCTS, STOCK
from psycopg.conninfo import make_conninfo

from retail_common.logging import configure_logging

_log = structlog.get_logger("seed")

CATALOG_TABLES = ("categories", "products")


def seed_catalog(conninfo: str) -> dict[str, int]:
    """Insert categories and products; raises if the schema has not been migrated."""
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT bool_and(to_regclass(%s || t) IS NOT NULL) FROM unnest(%s::text[]) AS t",
            ("public.", list(CATALOG_TABLES)),
        )
        row = cur.fetchone()
        if not (row and row[0]):
            # The tables come from the product-service migration (`product-migrate`), which this
            # script must not replace.
            msg = "product_db has no catalog tables; run `make up` so product-migrate applies them"
            raise RuntimeError(msg)

        categories = 0
        for slug, name in CATEGORIES:
            cur.execute(
                "INSERT INTO categories (slug, name) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
                (slug, name),
            )
            categories += cur.rowcount

        products = 0
        for product in PRODUCTS:
            cur.execute(
                "INSERT INTO products (sku, name, description, category_id, price, currency) "
                "SELECT %s, %s, %s, c.id, %s, 'USD' FROM categories c WHERE c.slug = %s "
                "ON CONFLICT (sku) DO NOTHING",
                (product.sku, product.name, product.description, product.price, product.category),
            )
            products += cur.rowcount
    return {"categories_inserted": categories, "products_inserted": products}


def seed_stock(dynamodb: Any) -> dict[str, int]:
    """Insert starting stock for any SKU that has no inventory item yet."""
    inserted = existing = 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for sku, quantity in STOCK.items():
        try:
            dynamodb.put_item(
                TableName="inventory",
                Item={
                    "sku": {"S": sku},
                    "available": {"N": str(quantity)},
                    "reserved": {"N": "0"},
                    "updated_at": {"S": now},
                },
                ConditionExpression="attribute_not_exists(sku)",
            )
            inserted += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing += 1
    return {"stock_inserted": inserted, "stock_already_present": existing}


def main() -> int:
    configure_logging("seed", os.environ.get("ENVIRONMENT", "local"), "INFO")
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

    catalog = seed_catalog(conninfo)
    stock = seed_stock(dynamodb)
    _log.info("seed_complete", **catalog, **stock)
    return 0


if __name__ == "__main__":
    sys.exit(main())

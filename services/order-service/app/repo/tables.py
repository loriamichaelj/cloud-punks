"""SQLAlchemy Core table definitions. They mirror migrations 0001 and 0002; the migrations are
authoritative."""

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

orders = Table(
    "orders",
    metadata,
    Column("order_id", CHAR(26), primary_key=True),
    Column("customer_id", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("status_reason", String(255)),
    Column("total_amount", Numeric(12, 2), nullable=False),
    Column("currency", CHAR(3), nullable=False),
    Column("idempotency_key", String(64), nullable=False),
    Column("request_hash", CHAR(64), nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),  # optimistic lock
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'REJECTED')", name="ck_orders_status"),
    UniqueConstraint("customer_id", "idempotency_key", name="uq_orders_customer_idem"),
)

order_items = Table(
    "order_items",
    metadata,
    Column("order_id", CHAR(26), ForeignKey("orders.order_id"), primary_key=True),
    Column("sku", String(64), primary_key=True),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
    Column("seller", String(64)),  # null: bought from the platform (migration 0002)
    CheckConstraint("quantity BETWEEN 1 AND 100", name="ck_order_items_quantity"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("event_id", CHAR(26), nullable=False, unique=True),
    Column("detail_type", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),  # the full envelope
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("published_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("last_error", String(512)),
    Index("ix_outbox_unpublished", "id", postgresql_where=text("published_at IS NULL")),
)

processed_events = Table(
    "processed_events",
    metadata,
    Column("event_id", CHAR(26), primary_key=True),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# -- the CloudPunks market (migration 0002, DESIGN.md section 16.5) ------------------------------

ACTIVE_LISTING = ("OPEN", "SALE_PENDING")

listings = Table(
    "listings",
    metadata,
    Column("listing_id", CHAR(26), primary_key=True),
    Column("sku", String(64), nullable=False),
    Column("seller_id", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    CheckConstraint(
        "status IN ('OPEN', 'SALE_PENDING', 'SOLD', 'CANCELLED')", name="ck_listings_status"
    ),
    Index(
        "uq_listings_active_sku",
        "sku",
        unique=True,
        postgresql_where=text("status IN ('OPEN', 'SALE_PENDING')"),
    ),
)

bids = Table(
    "bids",
    metadata,
    Column("bid_id", CHAR(26), primary_key=True),
    Column("listing_id", CHAR(26), ForeignKey("listings.listing_id"), nullable=False),
    Column("sku", String(64), nullable=False),
    Column("bidder_id", String(64), nullable=False),
    Column("amount", Numeric(10, 2), nullable=False),
    Column("currency", CHAR(3), nullable=False),
    Column("status", String(16), nullable=False),
    Column("order_id", CHAR(26), ForeignKey("orders.order_id")),
    Column("idempotency_key", String(64), nullable=False),
    Column("request_hash", CHAR(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
    CheckConstraint(
        "status IN ('OPEN', 'WITHDRAWN', 'ACCEPTED', 'FILLED', 'FAILED', 'CLOSED')",
        name="ck_bids_status",
    ),
    UniqueConstraint("bidder_id", "idempotency_key", name="uq_bids_bidder_idem"),
)

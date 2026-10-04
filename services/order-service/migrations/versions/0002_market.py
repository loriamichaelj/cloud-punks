"""The CloudPunks market: who an item was bought from, listings ("up for bid") and bids.

Expand only (DESIGN.md sections 5 and 16.5): a nullable column and two new tables, so the release
before this one runs unchanged on the new schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Null for a purchase from the platform; otherwise the customer it was bought from.
    op.add_column("order_items", sa.Column("seller", sa.String(64)))

    op.create_table(
        "listings",
        sa.Column("listing_id", sa.CHAR(26), primary_key=True),  # ULID
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("seller_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'SALE_PENDING', 'SOLD', 'CANCELLED')", name="ck_listings_status"
        ),
    )
    # At most one active listing per CloudPunk: putting it up twice is the same listing.
    op.create_index(
        "uq_listings_active_sku",
        "listings",
        ["sku"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'SALE_PENDING')"),
    )
    op.create_index("ix_listings_sku_created", "listings", ["sku", sa.text("created_at DESC")])

    op.create_table(
        "bids",
        sa.Column("bid_id", sa.CHAR(26), primary_key=True),  # ULID
        sa.Column("listing_id", sa.CHAR(26), sa.ForeignKey("listings.listing_id"), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("bidder_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("order_id", sa.CHAR(26), sa.ForeignKey("orders.order_id")),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),  # sha256 of the canonical body
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'WITHDRAWN', 'ACCEPTED', 'FILLED', 'FAILED', 'CLOSED')",
            name="ck_bids_status",
        ),
        sa.UniqueConstraint("bidder_id", "idempotency_key", name="uq_bids_bidder_idem"),
    )
    op.create_index(
        "ix_bids_listing_open",
        "bids",
        ["listing_id"],
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.create_index("ix_bids_sku_created", "bids", ["sku", sa.text("created_at DESC")])
    op.create_index("ix_bids_bidder", "bids", ["bidder_id", sa.text("created_at DESC")])
    # The order consumer finds the accepted bid behind an order when the order settles.
    op.create_index(
        "ix_bids_order", "bids", ["order_id"], postgresql_where=sa.text("order_id IS NOT NULL")
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only: rollbacks roll back code, not schema")

"""Create the order schema: orders, order_items, outbox, processed_events (DESIGN.md section 5).

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("order_id", sa.CHAR(26), primary_key=True),  # ULID
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_reason", sa.String(255)),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),  # sha256 of the canonical body
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A CHECK, not CREATE TYPE ... AS ENUM: adding a status later is a plain constraint swap,
        # which fits expand/contract better.
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'REJECTED')", name="ck_orders_status"
        ),
        sa.UniqueConstraint("customer_id", "idempotency_key", name="uq_orders_customer_idem"),
    )
    op.create_index(
        "ix_orders_customer_created",
        "orders",
        ["customer_id", sa.text("created_at DESC")],
    )
    # Powers the stuck-order sweeper (M8): PENDING orders are few; the old ones are the interest.
    op.create_index(
        "ix_orders_pending_created",
        "orders",
        ["created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "order_items",
        sa.Column("order_id", sa.CHAR(26), sa.ForeignKey("orders.order_id"), primary_key=True),
        sa.Column("sku", sa.String(64), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 100", name="ck_order_items_quantity"),
    )

    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("event_id", sa.CHAR(26), nullable=False),
        sa.Column("detail_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),  # the full envelope
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(512)),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
    )
    # The relay scans only unpublished rows, so the hot index stays tiny however big the table gets.
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.CHAR(26), primary_key=True),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only: rollbacks roll back code, not schema")

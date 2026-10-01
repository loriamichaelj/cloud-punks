"""Create the catalog: categories and products (DESIGN.md section 5).

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_table(
        "products",
        sa.Column("sku", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Set by the application on update; there is deliberately no trigger.
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
    )
    # PostgreSQL does not index foreign keys automatically.
    op.create_index(
        "ix_products_category_active",
        "products",
        ["category_id"],
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only: rollbacks roll back code, not schema")

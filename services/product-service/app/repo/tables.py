"""SQLAlchemy Core table definitions. They mirror migration 0001; the migration is authoritative."""

from sqlalchemy import (
    CHAR,
    Boolean,
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
    Text,
    func,
    text,
)

metadata = MetaData()

categories = Table(
    "categories",
    metadata,
    Column("id", Integer, Identity(always=True), primary_key=True),
    Column("slug", String(64), nullable=False, unique=True),
    Column("name", String(128), nullable=False),
)

products = Table(
    "products",
    metadata,
    Column("sku", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text),
    Column("category_id", Integer, ForeignKey("categories.id"), nullable=False),
    Column("price", Numeric(10, 2), nullable=False),
    Column("currency", CHAR(3), nullable=False, server_default=text("'USD'")),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Set by the app on update (no trigger), per DESIGN.md section 5.
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
    Index("ix_products_category_active", "category_id", postgresql_where=text("active")),
)

"""The seed dataset is plain data shipped from local/seed; check its shape without any store."""

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType

CATALOG_PATH = Path(__file__).resolve().parents[4] / "local" / "seed" / "catalog.py"


def load_catalog() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_catalog", CATALOG_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalog = load_catalog()


def test_five_categories_and_twenty_products() -> None:
    assert len(catalog.CATEGORIES) == 5
    assert len(catalog.PRODUCTS) == 20


def test_skus_are_unique_and_every_product_has_a_known_category() -> None:
    skus = [product.sku for product in catalog.PRODUCTS]
    slugs = {slug for slug, _name in catalog.CATEGORIES}
    assert len(set(skus)) == len(skus)
    assert {product.category for product in catalog.PRODUCTS} == slugs  # every category is used


def test_prices_are_two_decimal_places_never_floats() -> None:
    for product in catalog.PRODUCTS:
        assert isinstance(product.price, Decimal)
        assert product.price > 0
        assert product.price == product.price.quantize(Decimal("0.01"))


def test_every_product_has_stock_between_10_and_50() -> None:
    assert set(catalog.STOCK) == {product.sku for product in catalog.PRODUCTS}
    assert all(10 <= quantity <= 50 for quantity in catalog.STOCK.values())
    assert len(set(catalog.STOCK.values())) > 5  # varied, not one constant


def test_the_design_examples_are_seeded() -> None:
    by_sku = {product.sku: product for product in catalog.PRODUCTS}
    assert by_sku["SKU-TSHIRT-BLK-M"].price == Decimal("19.99")

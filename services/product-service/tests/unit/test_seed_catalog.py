"""The seed dataset is plain data shipped from local/seed; check its shape without any store."""

import importlib.util
import re
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


def test_five_types_and_one_hundred_cloudpunks() -> None:
    assert [slug for slug, _name in catalog.CATEGORIES] == [
        "male",
        "female",
        "zombie",
        "ape",
        "alien",
    ]
    assert [p.sku for p in catalog.PRODUCTS] == [f"CP-{n:04d}" for n in range(1, 101)]


def test_every_cloudpunk_has_a_known_type_and_every_type_is_used() -> None:
    slugs = {slug for slug, _name in catalog.CATEGORIES}
    assert {product.category for product in catalog.PRODUCTS} == slugs


def test_names_and_descriptions_follow_the_collection() -> None:
    for product in catalog.PRODUCTS:
        assert product.name == f"CloudPunk #{product.sku[3:]}"
        assert re.fullmatch(r"(Male|Female|Zombie|Ape|Alien) · .+", product.description), product


def test_prices_are_eth_with_two_decimal_places_never_floats() -> None:
    for product in catalog.PRODUCTS:
        assert isinstance(product.price, Decimal)
        assert product.price > 0
        assert product.price == product.price.quantize(Decimal("0.01"))
        assert product.currency == "ETH"


def test_one_of_each() -> None:
    assert {product.sku: 1 for product in catalog.PRODUCTS} == catalog.STOCK


def test_the_retired_retail_catalog_is_listed_and_not_reseeded() -> None:
    assert len(catalog.RETIRED_SKUS) == 20
    assert len(catalog.RETIRED_CATEGORIES) == 5
    assert not set(catalog.RETIRED_SKUS) & {p.sku for p in catalog.PRODUCTS}
    assert not set(catalog.RETIRED_CATEGORIES) & {slug for slug, _ in catalog.CATEGORIES}


def test_the_approved_first_cloudpunk_is_seeded() -> None:
    first = catalog.PRODUCTS[0]
    assert first.description == "Male · Mohawk Thin, Classic Shades, Cigarette, Earring"
    assert first.category == "male"

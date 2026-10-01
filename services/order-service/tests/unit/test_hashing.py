import re

from app.domain.hashing import request_hash
from app.domain.models import OrderLine

A, B = OrderLine("SKU-A", 2), OrderLine("SKU-B", 1)


def test_the_hash_is_64_lowercase_hex_chars() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", request_hash("cust-1", [A]))


def test_the_same_request_always_hashes_the_same() -> None:
    assert request_hash("cust-1", [A, B]) == request_hash("cust-1", [A, B])


def test_item_order_does_not_change_the_hash() -> None:
    """Retrying a request with its items shuffled is still the same request."""
    assert request_hash("cust-1", [A, B]) == request_hash("cust-1", [B, A])


def test_any_difference_in_the_request_changes_the_hash() -> None:
    base = request_hash("cust-1", [A, B])
    assert request_hash("cust-2", [A, B]) != base  # customer
    assert request_hash("cust-1", [OrderLine("SKU-A", 3), B]) != base  # quantity
    assert request_hash("cust-1", [A, OrderLine("SKU-C", 1)]) != base  # sku
    assert request_hash("cust-1", [A]) != base  # an item dropped


def test_boundaries_cannot_be_forged_by_concatenation() -> None:
    """("a", sku "bc") must not collide with ("ab", sku "c")."""
    assert request_hash("a", [OrderLine("bc", 1)]) != request_hash("ab", [OrderLine("c", 1)])

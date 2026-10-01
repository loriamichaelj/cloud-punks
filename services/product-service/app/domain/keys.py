"""Cache key layout and TTLs (DESIGN.md section 5, "Cache design")."""

PRODUCT_TTL_S = 300
LIST_TTL_S = 300
CATEGORIES_TTL_S = 3600

CATEGORIES_KEY = "categories:v1"
# Tracks every list key currently cached, so a write can delete them without `KEYS *`/SCAN.
LIST_KEYS_SET = "products:v1:listkeys"

# Only the first pages are cached. Without a bound, a client walking page=1..N with many sizes
# could grow the key space and the tracking set without limit.
MAX_CACHED_PAGE = 50

ALL_CATEGORIES = "_all"  # not a valid slug (slugs are [a-z0-9-]), so it cannot collide


def product_key(sku: str) -> str:
    return f"product:v1:{sku}"


def list_key(category: str | None, page: int, size: int) -> str:
    return f"products:v1:list:{category or ALL_CATEGORIES}:{page}:{size}"

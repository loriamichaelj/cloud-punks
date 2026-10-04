"""The seed dataset: the CloudPunks collection (DESIGN.md section 16.3, 16.7).

Five types as categories, 100 one-of-a-kind products priced in ETH, and one unit of stock each.
The product records come from ``cloudpunks.json``, which ``make cloudpunks`` generates with the
art, so a CloudPunk's description always matches its picture. Plain data and a file read, no store,
so it is unit-tested without anything running.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

COLLECTION_FILE = Path(__file__).resolve().parent / "cloudpunks.json"

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("male", "Male"),
    ("female", "Female"),
    ("zombie", "Zombie"),
    ("ape", "Ape"),
    ("alien", "Alien"),
)

# The retail catalog this collection replaced. The seed removes it from a store that still has it,
# so an environment seeded before the redesign ends up with the collection only.
RETIRED_CATEGORIES: tuple[str, ...] = ("apparel", "footwear", "accessories", "home", "electronics")
RETIRED_SKUS: tuple[str, ...] = (
    "SKU-TSHIRT-BLK-M",
    "SKU-TSHIRT-WHT-L",
    "SKU-HOODIE-GRY-M",
    "SKU-JEANS-BLU-32",
    "SKU-SNEAKER-WHT-42",
    "SKU-BOOT-BRN-43",
    "SKU-SANDAL-BLK-40",
    "SKU-SLIPPER-GRY-41",
    "SKU-CAP-NAVY",
    "SKU-BELT-BLK-95",
    "SKU-WALLET-BRN",
    "SKU-SCARF-RED",
    "SKU-MUG-WHT",
    "SKU-CANDLE-VAN",
    "SKU-THROW-GRY",
    "SKU-VASE-GLS",
    "SKU-EARBUDS-BLK",
    "SKU-CHARGER-USBC",
    "SKU-SPEAKER-MINI",
    "SKU-CABLE-USBC-2M",
)


@dataclass(frozen=True)
class SeedProduct:
    sku: str
    name: str
    description: str
    category: str  # a slug from CATEGORIES
    price: Decimal  # never a float
    currency: str


def _load() -> tuple[SeedProduct, ...]:
    records = json.loads(COLLECTION_FILE.read_text(), parse_float=Decimal)
    return tuple(
        SeedProduct(
            sku=r["sku"],
            name=r["name"],
            description=r["description"],
            category=r["category"],
            price=Decimal(r["price"]),  # a string in the file, so no float ever touches it
            currency=r["currency"],
        )
        for r in records
    )


PRODUCTS: tuple[SeedProduct, ...] = _load()

# One of each: a CloudPunk is a single item.
STOCK: dict[str, int] = {product.sku: 1 for product in PRODUCTS}

"""The seed dataset: 5 categories, 20 products, and a starting stock level for each.

Plain data, no I/O, so it is unit-tested without any store running.
"""

from dataclasses import dataclass
from decimal import Decimal

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("apparel", "Apparel"),
    ("footwear", "Footwear"),
    ("accessories", "Accessories"),
    ("home", "Home"),
    ("electronics", "Electronics"),
)


@dataclass(frozen=True)
class SeedProduct:
    sku: str
    name: str
    description: str
    category: str  # a slug from CATEGORIES
    price: Decimal  # never a float


def _p(sku: str, name: str, description: str, category: str, price: str) -> SeedProduct:
    return SeedProduct(sku, name, description, category, Decimal(price))


PRODUCTS: tuple[SeedProduct, ...] = (
    _p("SKU-TSHIRT-BLK-M", "Black T-Shirt (M)", "Soft cotton crew-neck tee.", "apparel", "19.99"),
    _p("SKU-TSHIRT-WHT-L", "White T-Shirt (L)", "Soft cotton crew-neck tee.", "apparel", "19.99"),
    _p(
        "SKU-HOODIE-GRY-M",
        "Grey Hoodie (M)",
        "Midweight fleece pullover hoodie.",
        "apparel",
        "49.99",
    ),
    _p("SKU-JEANS-BLU-32", "Blue Jeans (32)", "Straight-fit denim jeans.", "apparel", "59.99"),
    _p(
        "SKU-SNEAKER-WHT-42",
        "White Sneakers (42)",
        "Low-top leather sneakers.",
        "footwear",
        "89.00",
    ),
    _p("SKU-BOOT-BRN-43", "Brown Boots (43)", "Waxed leather lace-up boots.", "footwear", "129.50"),
    _p(
        "SKU-SANDAL-BLK-40",
        "Black Sandals (40)",
        "Adjustable-strap summer sandals.",
        "footwear",
        "34.99",
    ),
    _p(
        "SKU-SLIPPER-GRY-41", "Grey Slippers (41)", "Warm felt house slippers.", "footwear", "24.99"
    ),
    _p("SKU-CAP-NAVY", "Navy Cap", "Adjustable six-panel cotton cap.", "accessories", "15.99"),
    _p("SKU-BELT-BLK-95", "Black Belt (95 cm)", "Full-grain leather belt.", "accessories", "27.50"),
    _p("SKU-WALLET-BRN", "Brown Wallet", "Bifold leather wallet.", "accessories", "39.00"),
    _p("SKU-SCARF-RED", "Red Scarf", "Lightweight wool-blend scarf.", "accessories", "22.00"),
    _p("SKU-MUG-WHT", "White Mug", "350 ml stoneware mug.", "home", "8.99"),
    _p("SKU-CANDLE-VAN", "Vanilla Candle", "Hand-poured soy candle.", "home", "14.50"),
    _p("SKU-THROW-GRY", "Grey Throw", "Knitted cotton throw blanket.", "home", "44.00"),
    _p("SKU-VASE-GLS", "Glass Vase", "Hand-blown clear glass vase.", "home", "31.25"),
    _p(
        "SKU-EARBUDS-BLK",
        "Wireless Earbuds",
        "Bluetooth earbuds with charging case.",
        "electronics",
        "59.99",
    ),
    _p("SKU-CHARGER-USBC", "USB-C Charger", "30 W wall charger.", "electronics", "25.99"),
    _p("SKU-SPEAKER-MINI", "Mini Speaker", "Portable Bluetooth speaker.", "electronics", "49.50"),
    _p(
        "SKU-CABLE-USBC-2M",
        "USB-C Cable (2 m)",
        "Braided USB-C charging cable.",
        "electronics",
        "12.99",
    ),
)


def stock_for(index: int) -> int:
    """Deterministic starting stock between 10 and 50 inclusive, varied across the catalog."""
    return 10 + (index * 13) % 41


STOCK: dict[str, int] = {product.sku: stock_for(i) for i, product in enumerate(PRODUCTS)}

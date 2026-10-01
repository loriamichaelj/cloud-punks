// Product artwork: local SVG files (no external requests; the CSP allows img-src 'self'). The API
// has no image field, so the art is matched to a product by SKU. A product with no artwork (one
// created through the demo tools, say) falls back to its category icon.

export const CATEGORIES = ['apparel', 'footwear', 'accessories', 'home', 'electronics'] as const;
export type KnownCategory = (typeof CATEGORIES)[number];

const files = import.meta.glob<string>('./products/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
});

const artBySku = new Map<string, string>(
  Object.entries(files).map(([path, url]) => [
    path.replace(/^.*\//, '').replace(/\.svg$/, ''),
    url,
  ]),
);

/** The seeded catalog's categories, so a basket line (which stores no category) is tinted too. */
const CATEGORY_OF: Record<string, KnownCategory> = {
  'sku-tshirt-blk-m': 'apparel',
  'sku-tshirt-wht-l': 'apparel',
  'sku-hoodie-gry-m': 'apparel',
  'sku-jeans-blu-32': 'apparel',
  'sku-sneaker-wht-42': 'footwear',
  'sku-boot-brn-43': 'footwear',
  'sku-sandal-blk-40': 'footwear',
  'sku-slipper-gry-41': 'footwear',
  'sku-cap-navy': 'accessories',
  'sku-belt-blk-95': 'accessories',
  'sku-wallet-brn': 'accessories',
  'sku-scarf-red': 'accessories',
  'sku-mug-wht': 'home',
  'sku-candle-van': 'home',
  'sku-throw-gry': 'home',
  'sku-vase-gls': 'home',
  'sku-earbuds-blk': 'electronics',
  'sku-charger-usbc': 'electronics',
  'sku-speaker-mini': 'electronics',
  'sku-cable-usbc-2m': 'electronics',
};

export function artFor(sku: string): string | undefined {
  return artBySku.get(sku.toLowerCase());
}

/** The category slug to tint with: the one the API gave, else the seeded catalog's. */
export function categoryFor(sku: string, given?: string): string | undefined {
  return given ?? CATEGORY_OF[sku.toLowerCase()];
}

export function isKnownCategory(slug: string | undefined): slug is KnownCategory {
  return CATEGORIES.some((c) => c === slug);
}

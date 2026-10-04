// CloudPunk artwork: the local SVGs copied from nft-collection/ by `make ui-art` (no external
// requests; the CSP allows img-src 'self'). The API has no image field, so the picture is matched
// by SKU: CP-0001 is cloudpunks/0001.svg. A product with no artwork (one created through the demo
// tools, say) falls back to its type icon.

export const CATEGORIES = ['male', 'female', 'zombie', 'ape', 'alien'] as const;
export type KnownCategory = (typeof CATEGORIES)[number];

const files = import.meta.glob<string>('./cloudpunks/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
});

const artByNumber = new Map<string, string>(
  Object.entries(files).map(([path, url]) => [
    path.replace(/^.*\//, '').replace(/\.svg$/, ''),
    url,
  ]),
);

export function artFor(sku: string): string | undefined {
  const match = /^cp-(\d{4})$/i.exec(sku);
  return match?.[1] ? artByNumber.get(match[1]) : undefined;
}

/** The type slug to tint with: the one the API gave (a basket line stores none). */
export function categoryFor(_sku: string, given?: string): string | undefined {
  return given;
}

export function isKnownCategory(slug: string | undefined): slug is KnownCategory {
  return CATEGORIES.some((c) => c === slug);
}

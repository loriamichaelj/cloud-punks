// The collection as the screens see it (DESIGN.md section 16): one CloudPunk per CP- product, its
// market state from inventory and the active listings, its traits from the product description,
// and the filters, sorting, rarity and header figures built on top. Pure: no React, no fetch.

import { compareDecimal, parseMinor } from './money';

/** Red: unsold, bought from the platform. Purple: up for bid. Blue: owned, not on the market. */
export type MarketState = 'unsold' | 'bid' | 'owned';

export const STATE_LABEL: Record<MarketState, string> = {
  unsold: 'Unsold',
  bid: 'Up for bid',
  owned: 'Owned',
};

export interface CloudPunk {
  sku: string;
  number: number;
  /** "#0042" */
  label: string;
  /** "CloudPunk #0042" */
  name: string;
  /** The type slug ("male") and its display name ("Male"). */
  type: string;
  typeName: string;
  /** The attributes after the type, in the description's order. */
  traits: string[];
  /** The mint price: what the platform sells it for while it is unsold. */
  price: string;
  currency: string;
  state: MarketState;
  /** The customer who owns it; null while the platform holds it. */
  owner: string | null;
  lastSale: { amount: string; currency: string } | null;
}

const SKU = /^CP-(\d{4})$/;

export function numberOf(sku: string): number | null {
  const match = SKU.exec(sku);
  return match?.[1] ? Number(match[1]) : null;
}

export function skuOf(number: number): string {
  return `CP-${String(number).padStart(4, '0')}`;
}

/** "42", "#42", "0042" or "CP-0042" -> 42 when it is one of the 100; otherwise null. */
export function parseNumber(text: string): number | null {
  const match = /^\s*(?:cp-|#)?0*(\d{1,4})\s*$/i.exec(text);
  if (!match?.[1]) return null;
  const n = Number(match[1]);
  return n >= 1 && n <= 100 ? n : null;
}

/** "Male · Mohawk Thin, Classic Shades" -> type "Male", traits ["Mohawk Thin", "Classic Shades"]. */
export function parseDescription(description: string | null | undefined): {
  typeName: string;
  traits: string[];
} {
  const [typeName = '', rest = ''] = (description ?? '').split(' · ');
  const traits = rest
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  return { typeName: typeName.trim(), traits };
}

export function stateOf(available: number, owner: string | null, listed: boolean): MarketState {
  if (listed) return 'bid';
  if (owner === null && available > 0) return 'unsold';
  return 'owned';
}

export interface ProductInput {
  sku: string;
  name: string;
  description?: string | null;
  category: string;
  price: string;
  currency: string;
}

export interface MarketInput {
  /** sku -> what inventory says: units available and the owner. */
  stock: ReadonlyMap<string, { available: number; owner: string | null }>;
  /** SKUs with an active listing (open or with a bid being confirmed). */
  listed: ReadonlySet<string>;
  /** sku -> the latest sale. */
  lastSales?: ReadonlyMap<string, { amount: string; currency: string }>;
}

export function buildCollection(
  products: readonly ProductInput[],
  market: MarketInput,
): CloudPunk[] {
  const punks: CloudPunk[] = [];
  for (const p of products) {
    const number = numberOf(p.sku);
    if (number === null) continue; // the e2e fixtures and anything else that is not a CloudPunk
    const { typeName, traits } = parseDescription(p.description);
    const stock = market.stock.get(p.sku);
    const owner = stock?.owner ?? null;
    punks.push({
      sku: p.sku,
      number,
      label: `#${String(number).padStart(4, '0')}`,
      name: p.name,
      type: p.category,
      typeName: typeName || p.category,
      traits,
      price: p.price,
      currency: p.currency,
      state: stateOf(stock?.available ?? 0, owner, market.listed.has(p.sku)),
      owner,
      lastSale: market.lastSales?.get(p.sku) ?? null,
    });
  }
  return punks.sort((a, b) => a.number - b.number);
}

// -- traits and rarity ----------------------------------------------------------------------

/** How many carry each trait (the type counts as a trait, prefixed "type:"). */
export function countTraits(
  entries: readonly { type: string; traits: readonly string[] }[],
): Map<string, number> {
  const counts = new Map<string, number>();
  const add = (key: string) => counts.set(key, (counts.get(key) ?? 0) + 1);
  for (const e of entries) {
    add(`type:${e.type}`);
    for (const t of e.traits) add(t);
  }
  return counts;
}

/** How many CloudPunks carry each trait and type. */
export function traitCounts(punks: readonly CloudPunk[]): Map<string, number> {
  return countTraits(punks);
}

/** The same counts straight from catalog products (the item page has no market state to wait for). */
export function productTraitCounts(products: readonly ProductInput[]): Map<string, number> {
  return countTraits(
    products
      .filter((p) => numberOf(p.sku) !== null)
      .map((p) => ({ type: p.category, traits: parseDescription(p.description).traits })),
  );
}

/** "7%" of the collection has it; at least "<1%" for something present but rarer than that. */
export function rarityPercent(count: number, total: number): string {
  if (total <= 0 || count <= 0) return '0%';
  const percent = Math.round((count * 100) / total);
  return percent === 0 ? '<1%' : `${percent}%`;
}

/** Higher is rarer: the sum over its type and traits of 1 / how many share each. Not money. */
export function rarityScore(punk: CloudPunk, counts: ReadonlyMap<string, number>): number {
  const keys = [`type:${punk.type}`, ...punk.traits];
  return keys.reduce((sum, key) => sum + 1 / (counts.get(key) ?? 1), 0);
}

// -- filters and sorting --------------------------------------------------------------------

export type SortKey = 'number' | 'price-asc' | 'price-desc' | 'rarest';

export const SORT_LABEL: Record<SortKey, string> = {
  'price-asc': 'Price low to high',
  'price-desc': 'Price high to low',
  number: 'Number',
  rarest: 'Rarest first',
};

export interface Filters {
  status: MarketState[];
  types: string[];
  traits: string[];
  /** Number of traits ("attribute count"). */
  counts: number[];
  q: string;
  sort: SortKey;
}

export const NO_FILTERS: Filters = {
  status: [],
  types: [],
  traits: [],
  counts: [],
  q: '',
  sort: 'price-asc',
};

const STATES: readonly MarketState[] = ['unsold', 'bid', 'owned'];
const SORTS: readonly SortKey[] = ['price-asc', 'price-desc', 'number', 'rarest'];

/** Filters live in the URL so a filtered view can be shared and survives a reload. */
export function filtersFromSearch(search: URLSearchParams): Filters {
  const sort = search.get('sort');
  return {
    status: search
      .getAll('status')
      .filter((s): s is MarketState => STATES.includes(s as MarketState)),
    types: search.getAll('type'),
    traits: search.getAll('trait'),
    counts: search
      .getAll('count')
      .map(Number)
      .filter((n) => Number.isInteger(n) && n >= 0),
    q: search.get('q') ?? '',
    sort: SORTS.includes(sort as SortKey) ? (sort as SortKey) : NO_FILTERS.sort,
  };
}

export function searchFromFilters(f: Filters): URLSearchParams {
  const search = new URLSearchParams();
  for (const s of f.status) search.append('status', s);
  for (const t of f.types) search.append('type', t);
  for (const t of f.traits) search.append('trait', t);
  for (const c of f.counts) search.append('count', String(c));
  if (f.q) search.set('q', f.q);
  if (f.sort !== NO_FILTERS.sort) search.set('sort', f.sort);
  return search;
}

export function activeFilterCount(f: Filters): number {
  return f.status.length + f.types.length + f.traits.length + f.counts.length + (f.q ? 1 : 0);
}

function matchesQuery(p: CloudPunk, q: string): boolean {
  const text = q.trim().toLowerCase();
  if (!text) return true;
  const number = parseNumber(text);
  if (number !== null) return p.number === number;
  return (
    p.name.toLowerCase().includes(text) ||
    p.typeName.toLowerCase().includes(text) ||
    p.traits.some((t) => t.toLowerCase().includes(text))
  );
}

/** Any of the chosen values within a group, every group at once. */
export function applyFilters(punks: readonly CloudPunk[], f: Filters): CloudPunk[] {
  return punks.filter(
    (p) =>
      (f.status.length === 0 || f.status.includes(p.state)) &&
      (f.types.length === 0 || f.types.includes(p.type)) &&
      (f.traits.length === 0 || p.traits.some((t) => f.traits.includes(t))) &&
      (f.counts.length === 0 || f.counts.includes(p.traits.length)) &&
      matchesQuery(p, f.q),
  );
}

/** A copy, sorted. Prices only exist for unsold CloudPunks, so the others follow, by number. */
export function sortPunks(
  punks: readonly CloudPunk[],
  key: SortKey,
  counts: ReadonlyMap<string, number>,
): CloudPunk[] {
  const byNumber = (a: CloudPunk, b: CloudPunk) => a.number - b.number;
  const copy = [...punks];
  if (key === 'number') return copy.sort(byNumber);
  if (key === 'rarest') {
    return copy.sort((a, b) => rarityScore(b, counts) - rarityScore(a, counts) || byNumber(a, b));
  }
  const direction = key === 'price-asc' ? 1 : -1;
  return copy.sort((a, b) => {
    const aPriced = a.state === 'unsold';
    const bPriced = b.state === 'unsold';
    if (aPriced !== bPriced) return aPriced ? -1 : 1;
    if (!aPriced) return byNumber(a, b);
    return direction * compareDecimal(a.price, b.price) || byNumber(a, b);
  });
}

// -- the header figures ---------------------------------------------------------------------

export interface CollectionStats {
  items: number;
  owners: number;
  unsold: number;
  upForBid: number;
  /** The cheapest unsold CloudPunk's price, exactly. */
  floor: { amount: string; currency: string } | null;
}

export function collectionStats(punks: readonly CloudPunk[]): CollectionStats {
  let floor: CloudPunk | null = null;
  for (const p of punks) {
    if (p.state !== 'unsold') continue;
    if (floor === null || parseMinor(p.price) < parseMinor(floor.price)) floor = p;
  }
  return {
    items: punks.length,
    owners: new Set(punks.map((p) => p.owner).filter((o) => o !== null)).size,
    unsold: punks.filter((p) => p.state === 'unsold').length,
    upForBid: punks.filter((p) => p.state === 'bid').length,
    floor: floor ? { amount: floor.price, currency: floor.currency } : null,
  };
}

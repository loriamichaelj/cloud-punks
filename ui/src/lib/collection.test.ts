import { describe, expect, it } from 'vitest';
import {
  NO_FILTERS,
  activeFilterCount,
  applyFilters,
  buildCollection,
  collectionStats,
  filtersFromSearch,
  numberOf,
  parseDescription,
  parseNumber,
  productTraitCounts,
  rarityPercent,
  rarityScore,
  searchFromFilters,
  skuOf,
  sortPunks,
  stateOf,
  traitCounts,
  type CloudPunk,
  type ProductInput,
} from './collection';

const product = (
  n: number,
  description: string,
  price: string,
  category = 'male',
): ProductInput => ({
  sku: skuOf(n),
  name: `CloudPunk #${String(n).padStart(4, '0')}`,
  description,
  category,
  price,
  currency: 'ETH',
});

const PRODUCTS: ProductInput[] = [
  product(3, 'Male · Cap, Earring', '20.00'),
  product(1, 'Male · Mohawk Thin, Classic Shades, Cigarette, Earring', '31.43'),
  product(2, 'Female · Pigtails, Hot Lipstick', '9.50', 'female'),
  product(4, 'Zombie · Cap, Pipe, Earring', '75.00', 'zombie'),
  {
    sku: 'E2E-A',
    name: 'End-to-end E2E-A',
    description: 'Test fixture',
    category: 'male',
    price: '10.00',
    currency: 'ETH',
  },
];

const STOCK = new Map<string, { available: number; owner: string | null }>([
  ['CP-0001', { available: 1, owner: null }],
  ['CP-0002', { available: 0, owner: 'cust-alice' }],
  ['CP-0003', { available: 0, owner: 'cust-bob' }],
  ['CP-0004', { available: 1, owner: null }],
]);

function collection(): CloudPunk[] {
  return buildCollection(PRODUCTS, {
    stock: STOCK,
    listed: new Set(['CP-0003']),
    lastSales: new Map([['CP-0002', { amount: '9.50', currency: 'ETH' }]]),
  });
}

describe('identities', () => {
  it('reads and writes the CP- SKU', () => {
    expect(numberOf('CP-0042')).toBe(42);
    expect(numberOf('E2E-A')).toBeNull();
    expect(skuOf(7)).toBe('CP-0007');
  });

  it.each([
    ['42', 42],
    ['#42', 42],
    ['0042', 42],
    ['cp-0042', 42],
    [' 100 ', 100],
    ['0', null],
    ['101', null],
    ['punk', null],
  ])('parses %j as %j', (text, n) => {
    expect(parseNumber(text)).toBe(n);
  });

  it('splits the description into the type and its traits', () => {
    expect(parseDescription('Male · Mohawk Thin, Classic Shades')).toEqual({
      typeName: 'Male',
      traits: ['Mohawk Thin', 'Classic Shades'],
    });
    expect(parseDescription('Alien')).toEqual({ typeName: 'Alien', traits: [] });
    expect(parseDescription(null)).toEqual({ typeName: '', traits: [] });
  });
});

describe('market state (DESIGN.md 16.1)', () => {
  it.each([
    [1, null, false, 'unsold'],
    [0, 'cust-1', false, 'owned'],
    [0, 'cust-1', true, 'bid'],
    [0, null, false, 'owned'], // the platform holds it but has none to sell: not red
  ] as const)('available %i, owner %j, listed %j is %s', (available, owner, listed, state) => {
    expect(stateOf(available, owner, listed)).toBe(state);
  });

  it('builds only CloudPunks, in number order, with state, owner and last sale', () => {
    const punks = collection();
    expect(punks.map((p) => [p.number, p.state, p.owner])).toEqual([
      [1, 'unsold', null],
      [2, 'owned', 'cust-alice'],
      [3, 'bid', 'cust-bob'],
      [4, 'unsold', null],
    ]);
    expect(punks[1]?.lastSale).toEqual({ amount: '9.50', currency: 'ETH' });
    expect(punks[0]).toMatchObject({
      label: '#0001',
      typeName: 'Male',
      traits: ['Mohawk Thin', 'Classic Shades', 'Cigarette', 'Earring'],
    });
  });

  it('treats a CloudPunk inventory does not know yet as not for sale', () => {
    const [punk] = buildCollection([product(9, 'Ape · Cap', '150.00', 'ape')], {
      stock: new Map(),
      listed: new Set(),
    });
    expect(punk?.state).toBe('owned');
    expect(punk?.owner).toBeNull();
  });
});

describe('traits and rarity', () => {
  it('counts each trait and type', () => {
    const counts = traitCounts(collection());
    expect(counts.get('Earring')).toBe(3);
    expect(counts.get('Cap')).toBe(2);
    expect(counts.get('type:male')).toBe(2);
    expect(counts.get('type:zombie')).toBe(1);
  });

  it.each([
    [7, 100, '7%'],
    [1, 300, '<1%'],
    [0, 100, '0%'],
    [3, 0, '0%'],
  ])('%i of %i is %s', (count, total, text) => {
    expect(rarityPercent(count, total)).toBe(text);
  });

  it('counts the same straight from catalog products, CloudPunks only', () => {
    const counts = productTraitCounts(PRODUCTS);
    expect(counts.get('Earring')).toBe(3);
    expect(counts.get('type:male')).toBe(2); // E2E-A is not a CloudPunk
  });

  it('scores a CloudPunk higher the rarer its type and traits are', () => {
    const punks = collection();
    const counts = traitCounts(punks);
    const zombie = punks.find((p) => p.number === 4)!;
    const plain = punks.find((p) => p.number === 3)!;
    expect(rarityScore(zombie, counts)).toBeGreaterThan(rarityScore(plain, counts));
  });
});

describe('filters', () => {
  const punks = collection();
  const numbers = (list: CloudPunk[]) => list.map((p) => p.number);

  it('keeps everything with no filter', () => {
    expect(numbers(applyFilters(punks, NO_FILTERS))).toEqual([1, 2, 3, 4]);
  });

  it('matches any value within a group and every group at once', () => {
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, status: ['unsold', 'bid'] }))).toEqual([
      1, 3, 4,
    ]);
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, traits: ['Pipe', 'Pigtails'] }))).toEqual([
      2, 4,
    ]);
    expect(
      numbers(applyFilters(punks, { ...NO_FILTERS, traits: ['Cap'], status: ['unsold'] })),
    ).toEqual([4]);
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, types: ['female'] }))).toEqual([2]);
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, counts: [2] }))).toEqual([2, 3]);
  });

  it('searches by number or by text', () => {
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, q: '#4' }))).toEqual([4]);
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, q: 'lipstick' }))).toEqual([2]);
    expect(numbers(applyFilters(punks, { ...NO_FILTERS, q: 'zom' }))).toEqual([4]);
  });

  it('round-trips through the URL and ignores values it does not know', () => {
    const f = {
      status: ['bid' as const],
      types: ['ape'],
      traits: ['Cap', 'Pipe'],
      counts: [3],
      q: 'x',
      sort: 'rarest' as const,
    };
    expect(filtersFromSearch(searchFromFilters(f))).toEqual(f);
    expect(
      filtersFromSearch(new URLSearchParams('status=stolen&sort=cheapest&count=-1&count=a')),
    ).toEqual(NO_FILTERS);
    expect(searchFromFilters(NO_FILTERS).toString()).toBe('');
    expect(activeFilterCount(f)).toBe(6);
  });
});

describe('sorting', () => {
  const punks = collection();
  const counts = traitCounts(punks);
  const numbers = (key: Parameters<typeof sortPunks>[1]) =>
    sortPunks(punks, key, counts).map((p) => p.number);

  it('puts priced (unsold) CloudPunks first, by exact price, then the rest by number', () => {
    expect(numbers('price-asc')).toEqual([1, 4, 2, 3]);
    expect(numbers('price-desc')).toEqual([4, 1, 2, 3]);
  });

  it('sorts by number and by rarity', () => {
    expect(numbers('number')).toEqual([1, 2, 3, 4]);
    // sum of 1/count: #1 ~3.83 (three unique traits), #2 3.00, #4 ~2.83, #3 ~1.33
    expect(numbers('rarest')).toEqual([1, 2, 4, 3]);
  });

  it('does not change the list it was given', () => {
    const before = punks.map((p) => p.number);
    sortPunks(punks, 'price-desc', counts);
    expect(punks.map((p) => p.number)).toEqual(before);
  });
});

describe('collection stats', () => {
  it('counts items, owners, unsold and up for bid, and finds the floor exactly', () => {
    expect(collectionStats(collection())).toEqual({
      items: 4,
      owners: 2,
      unsold: 2,
      upForBid: 1,
      floor: { amount: '31.43', currency: 'ETH' },
    });
  });

  it('has no floor when nothing is unsold', () => {
    expect(collectionStats([]).floor).toBeNull();
  });
});

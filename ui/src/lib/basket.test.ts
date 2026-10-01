import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BASKET_KEY,
  MAX_LINES,
  MAX_QUANTITY,
  addToBasket,
  fingerprint,
  loadBasket,
  removeLine,
  saveBasket,
  setQuantity,
  type BasketLine,
} from './basket';

const line = (sku: string, quantity = 1): BasketLine => ({
  sku,
  name: `Product ${sku}`,
  unitPrice: '10.00',
  currency: 'USD',
  quantity,
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('basket editing', () => {
  it('adds a new line and merges quantities for an existing one', () => {
    const once = addToBasket([], line('A', 2)).lines;
    const twice = addToBasket(once, line('A', 3)).lines;
    expect(twice).toEqual([line('A', 5)]);
  });

  it('caps a line at 100 units', () => {
    const lines = addToBasket([line('A', 99)], line('A', 50)).lines;
    expect(lines[0]?.quantity).toBe(MAX_QUANTITY);
  });

  it('refuses a 21st distinct line and leaves the basket unchanged', () => {
    const full = Array.from({ length: MAX_LINES }, (_, i) => line(`S${i}`));
    const result = addToBasket(full, line('EXTRA'));
    expect(result.error).toBe('basket-full');
    expect(result.lines).toHaveLength(MAX_LINES);
  });

  it('still lets an existing line grow when the basket is full', () => {
    const full = Array.from({ length: MAX_LINES }, (_, i) => line(`S${i}`));
    expect(addToBasket(full, line('S3', 2)).error).toBeUndefined();
  });

  it('clamps edited quantities to 1..100 and survives nonsense', () => {
    const lines = [line('A', 5)];
    expect(setQuantity(lines, 'A', 0)[0]?.quantity).toBe(1);
    expect(setQuantity(lines, 'A', 1000)[0]?.quantity).toBe(100);
    expect(setQuantity(lines, 'A', Number.NaN)[0]?.quantity).toBe(1);
    expect(setQuantity(lines, 'A', 7.9)[0]?.quantity).toBe(7);
  });

  it('removes a line', () => {
    expect(removeLine([line('A'), line('B')], 'A').map((l) => l.sku)).toEqual(['B']);
  });
});

describe('persistence', () => {
  it('round-trips through localStorage', () => {
    saveBasket([line('A', 2)]);
    expect(loadBasket()).toEqual([line('A', 2)]);
  });

  it.each([
    ['not json', '{oops'],
    ['not an array', '{"a":1}'],
  ])('falls back to an empty basket for %s', (_name, raw) => {
    window.localStorage.setItem(BASKET_KEY, raw);
    expect(loadBasket()).toEqual([]);
  });

  it('drops malformed and duplicate lines but keeps the good ones', () => {
    window.localStorage.setItem(
      BASKET_KEY,
      JSON.stringify([
        line('A'),
        { sku: 'B' },
        line('A', 4),
        { ...line('C'), quantity: 0 },
        line('D'),
      ]),
    );
    expect(loadBasket().map((l) => l.sku)).toEqual(['A', 'D']);
  });

  it('works when localStorage throws (blocked storage)', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });
    expect(loadBasket()).toEqual([]);
    expect(() => {
      saveBasket([line('A')]);
    }).not.toThrow();
  });
});

describe('fingerprint', () => {
  it('ignores line order and depends on customer, SKUs and quantities', () => {
    const a = fingerprint('c1', [line('A', 1), line('B', 2)]);
    expect(fingerprint('c1', [line('B', 2), line('A', 1)])).toBe(a);
    expect(fingerprint('c2', [line('A', 1), line('B', 2)])).not.toBe(a);
    expect(fingerprint('c1', [line('A', 2), line('B', 2)])).not.toBe(a);
  });
});

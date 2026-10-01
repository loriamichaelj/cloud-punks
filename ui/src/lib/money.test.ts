import { describe, expect, it } from 'vitest';
import {
  MoneyParseError,
  addMinor,
  formatDecimal,
  formatMinor,
  minorToDecimal,
  parseMinor,
  timesMinor,
} from './money';

// A small deterministic generator, so "property" tests are reproducible.
function lcg(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s;
  };
}

describe('parseMinor', () => {
  it.each([
    ['0', 0n],
    ['0.00', 0n],
    ['5', 500n],
    ['5.5', 550n],
    ['129.50', 12950n],
    ['0.07', 7n],
    ['1000000.01', 100000001n],
  ])('%s -> %s', (text, expected) => {
    expect(parseMinor(text)).toBe(expected);
  });

  it.each(['', '-1.00', '+1.00', '1.234', '1,000.00', '1e3', 'abc', '.5', '1.', ' 1.00', '1.00 '])(
    'rejects %j',
    (text) => {
      expect(() => parseMinor(text)).toThrow(MoneyParseError);
    },
  );

  it('is exact where floating point is not (0.1 + 0.2)', () => {
    expect(minorToDecimal(addMinor(parseMinor('0.10'), parseMinor('0.20')))).toBe('0.30');
    expect(0.1 + 0.2).not.toBe(0.3);
  });
});

describe('round trips', () => {
  it('format(parse(x)) is x for any two-decimal amount', () => {
    const next = lcg(42);
    for (let i = 0; i < 500; i += 1) {
      const cents = next() % 10_000_000_000;
      const text = minorToDecimal(BigInt(cents));
      expect(minorToDecimal(parseMinor(text))).toBe(text);
      expect(text).toMatch(/^\d+\.\d{2}$/);
    }
  });

  it('addition and multiplication agree with repeated addition', () => {
    const next = lcg(7);
    for (let i = 0; i < 200; i += 1) {
      const unit = BigInt(next() % 1_000_000);
      const quantity = (next() % 100) + 1;
      let sum = 0n;
      for (let q = 0; q < quantity; q += 1) sum = addMinor(sum, unit);
      expect(timesMinor(unit, quantity)).toBe(sum);
    }
  });

  it('keeps precision beyond Number.MAX_SAFE_INTEGER', () => {
    const big = parseMinor('999999999999.99');
    expect(minorToDecimal(timesMinor(big, 100))).toBe('99999999999999.00');
    expect(big * 100n).toBeGreaterThan(BigInt(Number.MAX_SAFE_INTEGER));
  });
});

describe('timesMinor', () => {
  it('rejects fractional and negative quantities', () => {
    expect(() => timesMinor(100n, 1.5)).toThrow(RangeError);
    expect(() => timesMinor(100n, -1)).toThrow(RangeError);
  });
});

describe('formatting', () => {
  it('formats by string handling with separators and a currency symbol', () => {
    expect(formatMinor(12950n, 'USD')).toBe('$129.50');
    expect(formatMinor(5n, 'USD')).toBe('$0.05');
    expect(formatMinor(123456789n, 'USD')).toBe('$1,234,567.89');
    expect(formatMinor(-250n, 'USD')).toBe('-$2.50');
    expect(formatMinor(1200n, 'CHF')).toBe('CHF 12.00');
    expect(formatDecimal('27.5', 'USD')).toBe('$27.50');
  });
});

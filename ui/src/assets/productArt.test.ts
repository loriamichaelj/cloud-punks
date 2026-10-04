import { describe, expect, it } from 'vitest';
import { artFor, categoryFor, isKnownCategory } from './productArt';

const COLLECTION = Array.from({ length: 100 }, (_, i) => `CP-${String(i + 1).padStart(4, '0')}`);

describe('CloudPunk art', () => {
  it('has a local picture for every CloudPunk', () => {
    for (const sku of COLLECTION) {
      expect(artFor(sku), sku).toBeTruthy();
    }
    expect(new Set(COLLECTION.map(artFor)).size).toBe(100);
  });

  it('matches SKUs case-insensitively and never points off-site', () => {
    expect(artFor('cp-0001')).toBe(artFor('CP-0001'));
    expect(artFor('CP-0001')).not.toMatch(/^https?:/);
  });

  it('has nothing for any other product, so the type icon is shown instead', () => {
    expect(artFor('CP-0101')).toBeUndefined();
    expect(artFor('E2E-A')).toBeUndefined();
    expect(artFor('CP-1')).toBeUndefined();
  });

  it('tints with the type the API gave and knows the five types', () => {
    expect(categoryFor('CP-0001', 'zombie')).toBe('zombie');
    expect(categoryFor('CP-0001')).toBeUndefined();
    for (const slug of ['male', 'female', 'zombie', 'ape', 'alien']) {
      expect(isKnownCategory(slug)).toBe(true);
    }
    expect(isKnownCategory('apparel')).toBe(false);
  });
});

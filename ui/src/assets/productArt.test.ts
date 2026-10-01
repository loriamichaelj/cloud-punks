import { describe, expect, it } from 'vitest';
import { artFor, categoryFor, isKnownCategory } from './productArt';

const SEEDED = [
  'SKU-TSHIRT-BLK-M',
  'SKU-TSHIRT-WHT-L',
  'SKU-HOODIE-GRY-M',
  'SKU-JEANS-BLU-32',
  'SKU-SNEAKER-WHT-42',
  'SKU-BOOT-BRN-43',
  'SKU-SANDAL-BLK-40',
  'SKU-SLIPPER-GRY-41',
  'SKU-CAP-NAVY',
  'SKU-BELT-BLK-95',
  'SKU-WALLET-BRN',
  'SKU-SCARF-RED',
  'SKU-MUG-WHT',
  'SKU-CANDLE-VAN',
  'SKU-THROW-GRY',
  'SKU-VASE-GLS',
  'SKU-EARBUDS-BLK',
  'SKU-CHARGER-USBC',
  'SKU-SPEAKER-MINI',
  'SKU-CABLE-USBC-2M',
];

describe('product art', () => {
  it('has a local picture and a category for every seeded product', () => {
    for (const sku of SEEDED) {
      expect(artFor(sku), sku).toBeTruthy();
      expect(isKnownCategory(categoryFor(sku)), sku).toBe(true);
    }
  });

  it('matches SKUs case-insensitively and never points off-site', () => {
    expect(artFor('sku-mug-wht')).toBe(artFor('SKU-MUG-WHT'));
    expect(artFor('SKU-MUG-WHT')).not.toMatch(/^https?:/);
  });

  it('has nothing for an unknown product, so the category icon is shown instead', () => {
    expect(artFor('SKU-NEW-THING')).toBeUndefined();
    expect(categoryFor('SKU-NEW-THING')).toBeUndefined();
  });

  it('prefers the category the API gave', () => {
    expect(categoryFor('SKU-MUG-WHT', 'electronics')).toBe('electronics');
  });
});

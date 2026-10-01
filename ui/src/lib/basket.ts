// The basket lives in the browser only (no server-side carts). It stores what the screens need
// to render offline of the API: SKU, name, the unit price as an API decimal string, quantity.

import { readJson, writeJson } from './storage';

export const BASKET_KEY = 'retail.basket.v1';
export const MAX_LINES = 20;
export const MAX_QUANTITY = 100;

export interface BasketLine {
  sku: string;
  name: string;
  unitPrice: string;
  currency: string;
  quantity: number;
}

function isLine(value: unknown): value is BasketLine {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.sku === 'string' &&
    typeof v.name === 'string' &&
    typeof v.unitPrice === 'string' &&
    typeof v.currency === 'string' &&
    typeof v.quantity === 'number' &&
    Number.isInteger(v.quantity) &&
    v.quantity >= 1 &&
    v.quantity <= MAX_QUANTITY
  );
}

/** The stored basket, or an empty one when storage is blocked, empty or corrupt. */
export function loadBasket(): BasketLine[] {
  const raw = readJson(BASKET_KEY);
  if (!Array.isArray(raw)) return [];
  const lines: BasketLine[] = [];
  for (const item of raw as unknown[]) {
    if (!isLine(item) || lines.some((l) => l.sku === item.sku)) continue;
    lines.push(item);
    if (lines.length === MAX_LINES) break;
  }
  return lines;
}

export function saveBasket(lines: readonly BasketLine[]): void {
  writeJson(BASKET_KEY, lines);
}

export type AddResult = { lines: BasketLine[]; error?: 'basket-full' };

/** Add a product, or raise the quantity of an existing line (capped at MAX_QUANTITY). */
export function addToBasket(lines: readonly BasketLine[], line: BasketLine): AddResult {
  const existing = lines.find((l) => l.sku === line.sku);
  if (existing) {
    const quantity = Math.min(existing.quantity + line.quantity, MAX_QUANTITY);
    return { lines: lines.map((l) => (l.sku === line.sku ? { ...l, quantity } : l)) };
  }
  if (lines.length >= MAX_LINES) return { lines: [...lines], error: 'basket-full' };
  return { lines: [...lines, { ...line, quantity: Math.min(line.quantity, MAX_QUANTITY) }] };
}

export function setQuantity(
  lines: readonly BasketLine[],
  sku: string,
  quantity: number,
): BasketLine[] {
  const clamped = Math.max(1, Math.min(Math.trunc(quantity) || 1, MAX_QUANTITY));
  return lines.map((l) => (l.sku === sku ? { ...l, quantity: clamped } : l));
}

export function removeLine(lines: readonly BasketLine[], sku: string): BasketLine[] {
  return lines.filter((l) => l.sku !== sku);
}

/** Order-independent identity of a basket, used to decide whether an idempotency key is reusable. */
export function fingerprint(customerId: string, lines: readonly BasketLine[]): string {
  const parts = lines.map((l) => `${l.sku}x${l.quantity}`).sort();
  return `${customerId}|${parts.join(',')}`;
}

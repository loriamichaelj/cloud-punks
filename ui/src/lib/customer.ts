// The customer id is a demo label, not a credential (there is no login). It is generated once,
// kept in localStorage and editable, validated against the order API's pattern. The customers this
// browser has acted as are remembered too, so a tester can switch between them to buy, list and
// bid as several people.

import { readJson, readText, writeJson, writeText } from './storage';

export const CUSTOMER_KEY = 'retail.customer.v1';
export const KNOWN_CUSTOMERS_KEY = 'cloudpunks.customers.v1';
/** Enough for any test of the market; the oldest is dropped past it. */
export const MAX_KNOWN_CUSTOMERS = 20;
export const CUSTOMER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;

export function isValidCustomerId(value: string): boolean {
  return CUSTOMER_PATTERN.test(value);
}

export function generateCustomerId(): string {
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  return `cust-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}

export function loadCustomerId(): string {
  const stored = readText(CUSTOMER_KEY);
  if (stored !== null && isValidCustomerId(stored)) return stored;
  const created = generateCustomerId();
  writeText(CUSTOMER_KEY, created);
  return created;
}

export function saveCustomerId(value: string): boolean {
  return isValidCustomerId(value) && writeText(CUSTOMER_KEY, value);
}

/** The customers this browser has acted as, oldest first, always including ``current``. */
export function loadKnownCustomers(current: string): string[] {
  const stored = readJson(KNOWN_CUSTOMERS_KEY);
  const known = Array.isArray(stored)
    ? stored.filter((v): v is string => typeof v === 'string' && isValidCustomerId(v))
    : [];
  return withCustomer([...new Set(known)], current);
}

/** ``known`` with ``id`` added at the end (if new), trimmed to the newest MAX_KNOWN_CUSTOMERS. */
export function withCustomer(known: readonly string[], id: string): string[] {
  const list = known.includes(id) ? [...known] : [...known, id];
  return list.slice(-MAX_KNOWN_CUSTOMERS);
}

export function saveKnownCustomers(known: readonly string[]): void {
  writeJson(KNOWN_CUSTOMERS_KEY, known);
}

/** The id for a new customer: the name typed (if valid), or a generated one when it is blank.
 * Null when the name is not a valid id. */
export function newCustomerId(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed === '') return generateCustomerId();
  return isValidCustomerId(trimmed) ? trimmed : null;
}

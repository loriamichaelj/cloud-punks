// The customer id is a demo label, not a credential (there is no login). It is generated once,
// kept in localStorage and editable, validated against the order API's pattern.

import { readText, writeText } from './storage';

export const CUSTOMER_KEY = 'retail.customer.v1';
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

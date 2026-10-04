import { describe, expect, it, vi } from 'vitest';
import {
  CUSTOMER_KEY,
  KNOWN_CUSTOMERS_KEY,
  MAX_KNOWN_CUSTOMERS,
  generateCustomerId,
  isValidCustomerId,
  loadCustomerId,
  loadKnownCustomers,
  newCustomerId,
  saveCustomerId,
  saveKnownCustomers,
  withCustomer,
} from './customer';

describe('customer id', () => {
  it('is cust- plus 8 hex characters and valid for the API', () => {
    const id = generateCustomerId();
    expect(id).toMatch(/^cust-[0-9a-f]{8}$/);
    expect(isValidCustomerId(id)).toBe(true);
  });

  it('is generated once and then kept', () => {
    const first = loadCustomerId();
    expect(loadCustomerId()).toBe(first);
    expect(window.localStorage.getItem(CUSTOMER_KEY)).toBe(first);
  });

  it('replaces a stored value the API would reject', () => {
    window.localStorage.setItem(CUSTOMER_KEY, '-bad id!');
    expect(loadCustomerId()).toMatch(/^cust-/);
  });

  it('saves an edit only when it is valid', () => {
    expect(saveCustomerId('alice.demo')).toBe(true);
    expect(loadCustomerId()).toBe('alice.demo');
    expect(saveCustomerId('has space')).toBe(false);
    expect(saveCustomerId('')).toBe(false);
    expect(loadCustomerId()).toBe('alice.demo');
  });

  it('works when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    expect(loadCustomerId()).toMatch(/^cust-/);
    vi.restoreAllMocks();
  });
});

describe('known customers', () => {
  it('always include the current one, once', () => {
    expect(loadKnownCustomers('cust-a')).toEqual(['cust-a']);
    saveKnownCustomers(['cust-a', 'cust-b']);
    expect(loadKnownCustomers('cust-b')).toEqual(['cust-a', 'cust-b']);
  });

  it('drop what the API would refuse, duplicates and anything that is not a list', () => {
    window.localStorage.setItem(KNOWN_CUSTOMERS_KEY, JSON.stringify(['ok', 'ok', 'bad id!', 7]));
    expect(loadKnownCustomers('ok')).toEqual(['ok']);
    window.localStorage.setItem(KNOWN_CUSTOMERS_KEY, '{not json');
    expect(loadKnownCustomers('me')).toEqual(['me']);
    window.localStorage.setItem(KNOWN_CUSTOMERS_KEY, JSON.stringify({ a: 1 }));
    expect(loadKnownCustomers('me')).toEqual(['me']);
  });

  it('keep the newest when the list is full', () => {
    const many = Array.from({ length: MAX_KNOWN_CUSTOMERS }, (_, i) => `c-${i}`);
    const next = withCustomer(many, 'newest');
    expect(next).toHaveLength(MAX_KNOWN_CUSTOMERS);
    expect(next[0]).toBe('c-1');
    expect(next.at(-1)).toBe('newest');
    expect(withCustomer(many, 'c-3')).toEqual(many); // already known: unchanged
  });

  it('a new customer is the name typed, or a generated id when blank', () => {
    expect(newCustomerId('  bob ')).toBe('bob');
    expect(newCustomerId('')).toMatch(/^cust-[0-9a-f]{8}$/);
    expect(newCustomerId('has space')).toBeNull();
  });
});

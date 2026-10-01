import { describe, expect, it, vi } from 'vitest';
import {
  CUSTOMER_KEY,
  generateCustomerId,
  isValidCustomerId,
  loadCustomerId,
  saveCustomerId,
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

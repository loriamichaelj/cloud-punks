import { describe, expect, it } from 'vitest';
import { ATTEMPT_PREFIX, clearAttempt, keyFor } from './idempotency';

describe('idempotency keys', () => {
  it('reuses the key while the request is unchanged', () => {
    const first = keyFor('buy:CP-0042', 'cust-1');
    expect(keyFor('buy:CP-0042', 'cust-1')).toBe(first);
  });

  it('stores the attempt per scope', () => {
    const key = keyFor('bid:CP-0042', 'cust-1|25.00');
    expect(
      JSON.parse(window.localStorage.getItem(`${ATTEMPT_PREFIX}bid:CP-0042`) ?? 'null'),
    ).toEqual({
      fingerprint: 'cust-1|25.00',
      key,
    });
  });

  it('gives a changed request a new key, and keeps scopes apart', () => {
    const bid = keyFor('bid:CP-0042', 'cust-1|25.00');
    const higher = keyFor('bid:CP-0042', 'cust-1|26.00');
    expect(higher).not.toBe(bid);
    expect(keyFor('buy:CP-0042', 'cust-1')).not.toBe(higher);
    expect(keyFor('bid:CP-0042', 'cust-1|26.00')).toBe(higher);
  });

  it('starts afresh once the attempt is cleared', () => {
    const first = keyFor('buy:CP-0001', 'cust-1');
    clearAttempt('buy:CP-0001');
    expect(keyFor('buy:CP-0001', 'cust-1')).not.toBe(first);
  });

  it('still works when storage is blocked', () => {
    const original = window.localStorage.getItem.bind(window.localStorage);
    window.localStorage.getItem = () => {
      throw new Error('blocked');
    };
    try {
      expect(keyFor('buy:CP-0002', 'cust-1')).toMatch(/^[0-9a-f-]{32,36}$/);
    } finally {
      window.localStorage.getItem = original;
    }
  });
});

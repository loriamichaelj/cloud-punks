import { describe, expect, it, vi } from 'vitest';
import { ATTEMPT_KEY, clearAttempt, keyFor } from './idempotency';

describe('idempotency key lifecycle', () => {
  it('reuses the key while the basket is unchanged (retry, refresh, 503)', () => {
    const first = keyFor('c1|A x1');
    expect(keyFor('c1|A x1')).toBe(first);
  });

  it('survives a reload because it is stored', () => {
    const first = keyFor('c1|A x1');
    expect(JSON.parse(window.localStorage.getItem(ATTEMPT_KEY) ?? 'null')).toEqual({
      fingerprint: 'c1|A x1',
      key: first,
    });
  });

  it('issues a new key when the basket changes', () => {
    const first = keyFor('c1|A x1');
    const second = keyFor('c1|A x2');
    expect(second).not.toBe(first);
    expect(keyFor('c1|A x2')).toBe(second);
  });

  it('forgets the attempt once the order exists', () => {
    const first = keyFor('c1|A x1');
    clearAttempt();
    expect(keyFor('c1|A x1')).not.toBe(first);
  });

  it('matches the API pattern for keys', () => {
    expect(keyFor('c|x')).toMatch(/^[A-Za-z0-9._:-]{1,64}$/);
  });

  it('still returns a valid key where randomUUID is unavailable (plain http)', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
    try {
      expect(keyFor('c|insecure')).toMatch(/^[A-Za-z0-9._:-]{1,64}$/);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('ignores a corrupt stored attempt', () => {
    window.localStorage.setItem(ATTEMPT_KEY, '{"fingerprint":1}');
    expect(keyFor('c|x')).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('still returns a key when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    expect(keyFor('c|x')).toMatch(/^[0-9a-f-]{36}$/);
    vi.restoreAllMocks();
  });
});

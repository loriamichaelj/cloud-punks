import { afterEach, describe, expect, it, vi } from 'vitest';
import { newCorrelationId } from './correlation';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('newCorrelationId', () => {
  it('is unique per call', () => {
    expect(new Set(Array.from({ length: 100 }, newCorrelationId)).size).toBe(100);
  });

  it('is a safe header value of reasonable length', () => {
    expect(newCorrelationId()).toMatch(/^[A-Za-z0-9-]{16,64}$/);
  });

  it('falls back when randomUUID is unavailable (insecure context)', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
    expect(newCorrelationId()).toMatch(/^[0-9a-f]{32}$/);
  });
});

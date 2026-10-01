import { afterEach, describe, expect, it, vi } from 'vitest';
import { readJson, readText, removeKey, writeJson, writeText } from './storage';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('storage', () => {
  it('reads and writes text and json', () => {
    expect(writeText('k', 'v')).toBe(true);
    expect(readText('k')).toBe('v');
    expect(writeJson('j', { a: 1 })).toBe(true);
    expect(readJson('j')).toEqual({ a: 1 });
    removeKey('k');
    expect(readText('k')).toBeNull();
  });

  it('treats missing and corrupt json as null', () => {
    expect(readJson('missing')).toBeNull();
    window.localStorage.setItem('bad', '{');
    expect(readJson('bad')).toBeNull();
  });

  it('never throws when the browser blocks storage', () => {
    const boom = () => {
      throw new DOMException('blocked', 'SecurityError');
    };
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom);
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(boom);
    expect(readText('k')).toBeNull();
    expect(writeText('k', 'v')).toBe(false);
    expect(() => {
      removeKey('k');
    }).not.toThrow();
  });
});

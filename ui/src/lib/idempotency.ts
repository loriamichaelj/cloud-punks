// One Idempotency-Key per checkout attempt, stored with a fingerprint of the basket. The same key
// is reused on retry, refresh, network error and 503, so a double submit creates one order. A
// changed basket gets a new key: reusing the old one would be 422 IDEMPOTENCY_KEY_REUSED.

import { randomId } from './correlation';
import { readJson, removeKey, writeJson } from './storage';

export const ATTEMPT_KEY = 'retail.checkout.v1';

interface Attempt {
  fingerprint: string;
  key: string;
}

function isAttempt(value: unknown): value is Attempt {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.fingerprint === 'string' && typeof v.key === 'string' && v.key.length > 0;
}

function newKey(): string {
  return randomId();
}

/** The key for this basket: the stored one if the basket is unchanged, otherwise a fresh one. */
export function keyFor(fingerprint: string): string {
  const stored = readJson(ATTEMPT_KEY);
  if (isAttempt(stored) && stored.fingerprint === fingerprint) return stored.key;
  const key = newKey();
  writeJson(ATTEMPT_KEY, { fingerprint, key } satisfies Attempt);
  return key;
}

/** Forget the attempt once the order exists: the next checkout is a new order. */
export function clearAttempt(): void {
  removeKey(ATTEMPT_KEY);
}

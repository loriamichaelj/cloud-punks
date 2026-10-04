// One Idempotency-Key per action, stored with a fingerprint of what the action asks for. The same
// key is reused on retry, refresh, network error and 503, so a double submit is a replay, never a
// second order or bid. A changed request gets a new key: reusing the old one would be
// 422 IDEMPOTENCY_KEY_REUSED.
//
// Scopes: "buy:CP-0042" (buying one CloudPunk; fingerprint = the customer) and "bid:CP-0042"
// (a bid on it; fingerprint = the customer and the amount).

import { randomId } from './correlation';
import { readJson, removeKey, writeJson } from './storage';

export const ATTEMPT_PREFIX = 'cloudpunks.attempt.v1.';

interface Attempt {
  fingerprint: string;
  key: string;
}

function isAttempt(value: unknown): value is Attempt {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.fingerprint === 'string' && typeof v.key === 'string' && v.key.length > 0;
}

/** The key for this action: the stored one if the request is unchanged, otherwise a fresh one. */
export function keyFor(scope: string, fingerprint: string): string {
  const stored = readJson(ATTEMPT_PREFIX + scope);
  if (isAttempt(stored) && stored.fingerprint === fingerprint) return stored.key;
  const key = randomId();
  writeJson(ATTEMPT_PREFIX + scope, { fingerprint, key } satisfies Attempt);
  return key;
}

/** Forget the attempt once it succeeded: the next one is a new order or bid. */
export function clearAttempt(scope: string): void {
  removeKey(ATTEMPT_PREFIX + scope);
}

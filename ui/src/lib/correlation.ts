// One correlation id per user action, sent as X-Correlation-ID on every request it causes, so a
// click can be followed through the gateway, the services and the events.

export const CORRELATION_HEADER = 'X-Correlation-ID';

/** A random id that is safe in a header: a UUID, or 32 hex characters where randomUUID is missing. */
export function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // randomUUID needs a secure context; plain http://<lan-ip> is not one.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function newCorrelationId(): string {
  return randomId();
}

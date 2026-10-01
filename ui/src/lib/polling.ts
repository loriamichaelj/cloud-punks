// Order tracking schedule (DESIGN.md section 15.4): every 1 s for the first 10 s, then every 2 s,
// stopping at a terminal status or after 60 s ("still processing, refresh").

export const FAST_MS = 1000;
export const SLOW_MS = 2000;
export const FAST_WINDOW_MS = 10_000;
export const GIVE_UP_MS = 60_000;

export type OrderStatus = 'PENDING' | 'CONFIRMED' | 'REJECTED';

export function isTerminal(status: string): boolean {
  return status === 'CONFIRMED' || status === 'REJECTED';
}

/** Delay before the next poll given how long we have been watching, or false to stop. */
export function nextPollDelay(elapsedMs: number, status: string | undefined): number | false {
  if (status !== undefined && isTerminal(status)) return false;
  if (elapsedMs >= GIVE_UP_MS) return false;
  return elapsedMs < FAST_WINDOW_MS ? FAST_MS : SLOW_MS;
}

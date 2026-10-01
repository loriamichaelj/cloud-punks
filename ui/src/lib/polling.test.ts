import { describe, expect, it } from 'vitest';
import { GIVE_UP_MS, isTerminal, nextPollDelay } from './polling';

describe('order polling schedule', () => {
  it('polls every second for the first 10 seconds', () => {
    expect(nextPollDelay(0, 'PENDING')).toBe(1000);
    expect(nextPollDelay(9_999, 'PENDING')).toBe(1000);
  });

  it('then every two seconds', () => {
    expect(nextPollDelay(10_000, 'PENDING')).toBe(2000);
    expect(nextPollDelay(59_999, undefined)).toBe(2000);
  });

  it('gives up after 60 seconds', () => {
    expect(nextPollDelay(GIVE_UP_MS, 'PENDING')).toBe(false);
  });

  it.each(['CONFIRMED', 'REJECTED'])('stops at the terminal status %s', (status) => {
    expect(isTerminal(status)).toBe(true);
    expect(nextPollDelay(0, status)).toBe(false);
  });

  it('PENDING is not terminal', () => {
    expect(isTerminal('PENDING')).toBe(false);
  });
});

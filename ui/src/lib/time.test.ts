import { describe, expect, it } from 'vitest';
import { timeAgo } from './time';

const NOW = Date.parse('2026-10-04T12:00:00Z');

describe('timeAgo', () => {
  it.each([
    ['2026-10-04T11:59:30Z', 'just now'],
    ['2026-10-04T11:59:00Z', '1 minute ago'],
    ['2026-10-04T11:15:00Z', '45 minutes ago'],
    ['2026-10-04T09:00:00Z', '3 hours ago'],
    ['2026-10-03T12:00:00Z', '1 day ago'],
    ['2026-08-01T12:00:00Z', '2 months ago'],
    ['2024-10-04T12:00:00Z', '2 years ago'],
    ['2026-10-04T12:05:00Z', 'just now'], // a clock a little ahead is not "in the future"
  ])('%s is %s', (iso, text) => {
    expect(timeAgo(iso, NOW)).toBe(text);
  });

  it('is empty for something that is not a time', () => {
    expect(timeAgo('soon', NOW)).toBe('');
  });
});

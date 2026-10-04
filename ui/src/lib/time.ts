// "3 minutes ago", for activity rows. Plain arithmetic on milliseconds (never money).

const UNITS: [number, string][] = [
  [365 * 24 * 3600, 'year'],
  [30 * 24 * 3600, 'month'],
  [24 * 3600, 'day'],
  [3600, 'hour'],
  [60, 'minute'],
];

export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  if (Number.isNaN(seconds)) return '';
  if (seconds < 60) return 'just now';
  for (const [size, unit] of UNITS) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      return `${n} ${unit}${n === 1 ? '' : 's'} ago`;
    }
  }
  return 'just now'; // unreachable: a minute is the smallest unit above
}

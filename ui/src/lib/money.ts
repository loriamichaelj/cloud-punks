// Money is never a JS number (CLAUDE.md). API decimal strings are parsed into integer minor units
// (BigInt) for arithmetic and formatted by string handling. Totals computed here are estimates.

const DECIMAL = /^(\d{1,12})(?:\.(\d{1,2}))?$/;

export class MoneyParseError extends Error {
  constructor(value: string) {
    super(`not a money amount: ${JSON.stringify(value)}`);
    this.name = 'MoneyParseError';
  }
}

/** "129.50" -> 12950n. Accepts one or two decimals, no sign, no exponent, no separators. */
export function parseMinor(value: string): bigint {
  const match = DECIMAL.exec(value);
  if (!match) throw new MoneyParseError(value);
  const whole = match[1] ?? '0';
  const cents = (match[2] ?? '').padEnd(2, '0');
  return BigInt(whole) * 100n + BigInt(cents);
}

export function addMinor(a: bigint, b: bigint): bigint {
  return a + b;
}

export function timesMinor(unit: bigint, quantity: number): bigint {
  if (!Number.isInteger(quantity) || quantity < 0)
    throw new RangeError('quantity must be a whole number');
  return unit * BigInt(quantity);
}

/** 12950n -> "129.50", always two decimals. */
export function minorToDecimal(minor: bigint): string {
  const negative = minor < 0n;
  const digits = (negative ? -minor : minor).toString().padStart(3, '0');
  const whole = digits.slice(0, -2);
  return `${negative ? '-' : ''}${whole}.${digits.slice(-2)}`;
}

const SYMBOLS: Record<string, string> = { USD: '$', EUR: '€', GBP: '£' };

function groupThousands(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** 12950n, "USD" -> "$129.50"; an unknown currency is shown as a prefix code ("CHF 12.00"). */
export function formatMinor(minor: bigint, currency: string): string {
  const decimal = minorToDecimal(minor);
  const negative = decimal.startsWith('-');
  const [whole = '0', cents = '00'] = (negative ? decimal.slice(1) : decimal).split('.');
  const symbol = SYMBOLS[currency];
  const amount = `${groupThousands(whole)}.${cents}`;
  return `${negative ? '-' : ''}${symbol ?? `${currency} `}${amount}`;
}

/** Format an API decimal string without ever converting it to a number. */
export function formatDecimal(value: string, currency: string): string {
  return formatMinor(parseMinor(value), currency);
}

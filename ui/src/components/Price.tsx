import { formatDecimal } from '../lib/money';

/** An API decimal string shown as money; a value that is not money is shown as it came. */
export function formatPrice(value: string, currency: string): string {
  try {
    return formatDecimal(value, currency);
  } catch {
    return value;
  }
}

export function Price({ value, currency }: { value: string; currency: string }) {
  return <span>{formatPrice(value, currency)}</span>;
}

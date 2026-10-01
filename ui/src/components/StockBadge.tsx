import ui from '../styles/ui.module.css';

export const LOW_STOCK_BELOW = 5;

export function stockLabel(available: number): string {
  if (available <= 0) return 'Out of stock';
  if (available < LOW_STOCK_BELOW) return `Only ${available} left`;
  return 'In stock';
}

export function StockBadge({ available }: { available: number }) {
  const className =
    available <= 0 ? ui.badgeBad : available < LOW_STOCK_BELOW ? ui.badgeWarn : ui.badgeOk;
  return <span className={`${ui.badge} ${className}`}>{stockLabel(available)}</span>;
}

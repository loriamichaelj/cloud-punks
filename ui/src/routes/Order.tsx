import { Link, useParams } from 'react-router';
import { useGaveUp, useNotifications, useOrder } from '../api/hooks';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { ProductImage } from '../components/ProductImage';
import { Price, formatPrice } from '../components/Price';
import { minorToDecimal, parseMinor, timesMinor } from '../lib/money';
import { isTerminal } from '../lib/polling';
import ui from '../styles/ui.module.css';
import styles from './order.module.css';

const REASONS: Record<string, string> = {
  OUT_OF_STOCK: 'Some items ran out of stock before they could be reserved.',
  UNKNOWN_SKU: 'An item in the order is no longer sold.',
};

export function OrderPage() {
  const { id = '' } = useParams();
  const order = useOrder(id);
  const notifications = useNotifications(id, order.data?.status);
  const gaveUp = useGaveUp(order.data?.status);

  if (order.isPending) return <Loading what="the order" />;
  if (order.isError) {
    return (
      <ErrorPanel
        error={order.error}
        title="Could not load this order"
        onRetry={() => {
          void order.refetch();
        }}
      >
        <Link to="/orders">My orders</Link>
      </ErrorPanel>
    );
  }

  const o = order.data;
  const terminal = isTerminal(o.status);
  const statusText =
    o.status === 'CONFIRMED'
      ? 'Confirmed: your items are reserved.'
      : o.status === 'REJECTED'
        ? `Rejected. ${REASONS[o.status_reason ?? ''] ?? o.status_reason ?? ''}`
        : 'Pending: waiting for the warehouse to reserve your items.';

  return (
    <>
      <p>
        <Link to="/orders">← My orders</Link>
      </p>
      <h1>Order {o.order_id}</h1>

      <section className={ui.panel} aria-labelledby="status-heading">
        <h2 id="status-heading">Status</h2>
        <ol className={styles.timeline} aria-label="Order progress">
          <li className={`${styles.step} ${styles.done}`}>Placed</li>
          <li className={`${styles.step} ${styles.done}`}>Processing</li>
          <li
            className={`${styles.step} ${terminal ? styles.done : ''} ${
              o.status === 'REJECTED'
                ? styles.rejected
                : o.status === 'CONFIRMED'
                  ? styles.confirmed
                  : ''
            }`}
          >
            {o.status === 'REJECTED'
              ? 'Rejected'
              : o.status === 'CONFIRMED'
                ? 'Confirmed'
                : 'Confirmed or rejected'}
          </li>
        </ol>
        <p
          role="status"
          aria-live="polite"
          data-testid="order-status"
          data-status={o.status}
          className={`${styles.banner} ${
            o.status === 'CONFIRMED'
              ? styles.bannerConfirmed
              : o.status === 'REJECTED'
                ? styles.bannerRejected
                : styles.bannerPending
          }`}
        >
          <strong>{o.status}</strong>
          <span className="visually-hidden">. </span> {statusText}
        </p>
        {o.status === 'REJECTED' && o.status_reason && (
          <p>
            Reason: <code>{o.status_reason}</code>
          </p>
        )}
        {gaveUp && (
          <p className={`${ui.alert} ${ui.alertWarn}`} role="status">
            Still processing. This page stopped checking automatically; refresh it to look again.
          </p>
        )}
      </section>

      <section className={ui.panel} aria-labelledby="items-heading">
        <h2 id="items-heading">Items</h2>
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th scope="col">SKU</th>
                <th scope="col" className={ui.num}>
                  Quantity
                </th>
                <th scope="col" className={ui.num}>
                  Unit price
                </th>
                <th scope="col" className={ui.num}>
                  Line total
                </th>
              </tr>
            </thead>
            <tbody>
              {o.items.map((item) => (
                <tr key={item.sku}>
                  <td>
                    <div className={ui.lineItem}>
                      <ProductImage sku={item.sku} size="thumb" />
                      {item.sku}
                    </div>
                  </td>
                  <td className={ui.num}>{item.quantity}</td>
                  <td className={ui.num}>
                    <Price value={item.unit_price} currency={o.currency} />
                  </td>
                  <td className={ui.num}>
                    {formatPrice(
                      minorToDecimal(timesMinor(parseMinor(item.unit_price), item.quantity)),
                      o.currency,
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          <strong>
            Total: <Price value={o.total_amount} currency={o.currency} />
          </strong>{' '}
          <span className={ui.hint}>(unit prices were fixed when the order was placed)</span>
        </p>
        <p className={ui.hint}>
          Customer {o.customer_id} · placed {new Date(o.created_at).toLocaleString()}
        </p>
      </section>

      <section className={ui.panel} aria-labelledby="notes-heading">
        <h2 id="notes-heading">Notifications</h2>
        {notifications.isError && <p className={ui.fieldError}>Could not load notifications.</p>}
        {notifications.data?.items.length === 0 && (
          <p className={ui.muted}>None yet. They arrive a moment after each step.</p>
        )}
        <ul>
          {notifications.data?.items.map((n) => (
            <li key={n.event_id}>
              {n.message} <span className={ui.hint}>({n.type})</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

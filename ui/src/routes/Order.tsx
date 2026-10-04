import { Link, useParams } from 'react-router';
import { useGaveUp, useNotifications, useOrder } from '../api/hooks';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { formatPrice } from '../components/Price';
import { PunkImage } from '../components/PunkImage';
import { Who } from '../components/Who';
import { numberOf } from '../lib/collection';
import { isTerminal } from '../lib/polling';
import { useCustomer } from '../state';
import ui from '../styles/ui.module.css';
import styles from './order.module.css';

const REASONS: Record<string, string> = {
  OUT_OF_STOCK: 'Someone else got it first: it is no longer for sale by its seller.',
  UNKNOWN_SKU: 'This item is no longer sold.',
};

const itemName = (sku: string) =>
  numberOf(sku) === null ? sku : sku.replace('CP-', 'CloudPunk #');

/** One order, followed until inventory moves the CloudPunk (CONFIRMED) or cannot (REJECTED). */
export function OrderPage() {
  const { id = '' } = useParams();
  const { customerId } = useCustomer();
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
        <Link to="/account?tab=orders">My orders</Link>
      </ErrorPanel>
    );
  }

  const o = order.data;
  const item = o.items[0];
  const terminal = isTerminal(o.status);
  const buyer = o.customer_id === customerId ? 'You' : o.customer_id;
  const statusText =
    o.status === 'CONFIRMED'
      ? `${buyer} now own${buyer === 'You' ? '' : 's'} ${item ? itemName(item.sku) : 'it'}.`
      : o.status === 'REJECTED'
        ? (REASONS[o.status_reason ?? ''] ?? o.status_reason ?? 'The order was rejected.')
        : 'Waiting for the transfer to be confirmed.';

  return (
    <div className={styles.page}>
      <p>
        <Link to="/account?tab=orders">← My orders</Link>
      </p>
      <div className={styles.head}>
        {item && (
          <PunkImage
            sku={item.sku}
            state={o.status === 'CONFIRMED' ? 'owned' : undefined}
            size="card"
          />
        )}
        <div>
          <h1>{item ? itemName(item.sku) : 'Order'}</h1>
          <p className={ui.muted}>
            Order <span className={ui.correlation}>{o.order_id}</span>
          </p>
          <p className={styles.total}>{formatPrice(o.total_amount, o.currency)}</p>
          {item && (
            <p className={ui.muted}>
              Bought by <Who id={o.customer_id} /> from <Who id={item.seller ?? null} />
            </p>
          )}
        </div>
      </div>

      <section className={ui.panel} aria-labelledby="status-heading">
        <h2 id="status-heading" className={ui.panelTitle}>
          Status
        </h2>
        <ol className={styles.timeline} aria-label="Order progress">
          <li className={`${styles.step} ${styles.done}`}>Placed</li>
          <li className={`${styles.step} ${styles.done}`}>Transferring</li>
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
          className={`${ui.alert} ${
            o.status === 'CONFIRMED'
              ? ui.alertOk
              : o.status === 'REJECTED'
                ? ui.alertError
                : ui.alertInfo
          }`}
        >
          <strong>{o.status}</strong>
          <span className="visually-hidden">. </span> {statusText}
        </p>
        {o.status === 'REJECTED' && o.status_reason && (
          <p className={ui.hint}>
            Reason code: <code>{o.status_reason}</code>
          </p>
        )}
        {o.status === 'CONFIRMED' && item && (
          <p>
            <Link to={`/cloudpunks/${item.sku.slice(3)}`}>View {itemName(item.sku)}</Link>
          </p>
        )}
        {gaveUp && (
          <p className={`${ui.alert} ${ui.alertWarn}`} role="status">
            Still processing. This page stopped checking automatically; refresh it to look again.
          </p>
        )}
      </section>

      <section className={ui.panel} aria-labelledby="notes-heading">
        <h2 id="notes-heading" className={ui.panelTitle}>
          Notifications
        </h2>
        {notifications.isError && <p className={ui.fieldError}>Could not load notifications.</p>}
        {notifications.data?.items.length === 0 && (
          <p className={ui.muted}>None yet. They arrive a moment after each step.</p>
        )}
        <ul className={styles.notes}>
          {notifications.data?.items.map((n) => (
            <li key={n.event_id}>
              {n.message} <span className={ui.hint}>({n.type})</span>
            </li>
          ))}
        </ul>
        <p className={ui.hint}>Placed {new Date(o.created_at).toLocaleString()}</p>
      </section>
    </div>
  );
}

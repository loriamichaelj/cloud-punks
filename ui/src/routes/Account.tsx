import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { api } from '../api/endpoints';
import { MARKET_KEYS, useCollection, useMyBids, useOrders } from '../api/hooks';
import type { Bid } from '../api/types';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { Pagination } from '../components/Pagination';
import { formatPrice } from '../components/Price';
import { PunkCard } from '../components/PunkCard';
import { PunkImage } from '../components/PunkImage';
import { numberOf } from '../lib/collection';
import { timeAgo } from '../lib/time';
import { useCustomer } from '../state';
import ui from '../styles/ui.module.css';
import styles from './account.module.css';

type Tab = 'collected' | 'bids' | 'orders';
const TABS: { key: Tab; label: string }[] = [
  { key: 'collected', label: 'Collected' },
  { key: 'bids', label: 'Bids' },
  { key: 'orders', label: 'Orders' },
];

/** The customer's profile: what they own, the bids they made and the orders they placed. */
export function AccountPage() {
  const { customerId } = useCustomer();
  const [params] = useSearchParams();
  const tab: Tab = TABS.find((t) => t.key === params.get('tab'))?.key ?? 'collected';
  const collection = useCollection();
  const mine = (collection.punks ?? []).filter((p) => p.owner === customerId);
  const avatar = mine[0];

  return (
    <>
      <section className={styles.profile} aria-labelledby="profile-heading">
        <div className={styles.avatar}>
          {avatar ? (
            <PunkImage sku={avatar.sku} state={avatar.state} size="card" />
          ) : (
            <span className={styles.blank} aria-hidden="true" />
          )}
        </div>
        <div>
          <h1 id="profile-heading">My CloudPunks</h1>
          <p className={styles.address}>
            <span className={ui.correlation}>{customerId}</span>
          </p>
          <p className={ui.hint}>
            Your customer id is a demo label kept in this browser, not a wallet or a login.
          </p>
        </div>
      </section>

      <nav aria-label="Profile" className={ui.tabs}>
        {TABS.map((t) => (
          <Link
            key={t.key}
            to={t.key === 'collected' ? '/account' : `/account?tab=${t.key}`}
            aria-current={tab === t.key ? 'page' : undefined}
          >
            {t.label}
            {t.key === 'collected' && collection.punks ? ` ${mine.length}` : ''}
          </Link>
        ))}
      </nav>

      {tab === 'collected' &&
        (collection.isPending ? (
          <Loading what="your CloudPunks" />
        ) : collection.error ? (
          <ErrorPanel
            error={collection.error}
            title="Could not load your CloudPunks"
            onRetry={collection.refetch}
          />
        ) : mine.length === 0 ? (
          <p className={ui.empty}>
            You do not own a CloudPunk yet. <Link to="/?status=unsold">Buy an unsold one</Link>.
          </p>
        ) : (
          <ul className={styles.grid} aria-label="CloudPunks you own">
            {mine.map((punk) => (
              <PunkCard key={punk.sku} punk={punk} />
            ))}
          </ul>
        ))}
      {tab === 'bids' && <MyBids customerId={customerId} />}
      {tab === 'orders' && <MyOrders customerId={customerId} />}
    </>
  );
}

function MyBids({ customerId }: { customerId: string }) {
  const bids = useMyBids(customerId);
  const client = useQueryClient();
  const withdraw = useMutation({
    mutationFn: (bid: Bid) => api.withdrawBid(bid.bid_id, customerId),
    onSuccess: () => {
      for (const key of MARKET_KEYS) void client.invalidateQueries({ queryKey: [key] });
    },
  });
  if (bids.isPending) return <Loading what="your bids" />;
  if (bids.isError) {
    return (
      <ErrorPanel
        error={bids.error}
        title="Could not load your bids"
        onRetry={() => {
          void bids.refetch();
        }}
      />
    );
  }
  if (bids.data.items.length === 0) {
    return <p className={ui.empty}>No bids yet. Purple CloudPunks are up for bid.</p>;
  }
  return (
    <>
      {withdraw.isError && <ErrorPanel error={withdraw.error} title="Could not withdraw the bid" />}
      <div className={ui.tableWrap}>
        <table className={ui.table}>
          <caption className="visually-hidden">Your bids, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Item</th>
              <th scope="col" className={ui.num}>
                Price
              </th>
              <th scope="col">Status</th>
              <th scope="col">Time</th>
              <th scope="col">
                <span className="visually-hidden">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {bids.data.items.map((bid) => (
              <tr key={bid.bid_id}>
                <td>
                  <Link to={`/cloudpunks/${bid.sku.slice(3)}`} className={ui.lineItem}>
                    <PunkImage sku={bid.sku} state={undefined} size="mini" />
                    {numberOf(bid.sku) === null ? bid.sku : bid.sku.replace('CP-', 'CloudPunk #')}
                  </Link>
                </td>
                <td className={ui.num}>{formatPrice(bid.amount, bid.currency)}</td>
                <td>
                  <span className={ui.pill}>{bid.status.toLowerCase()}</span>
                </td>
                <td>{timeAgo(bid.created_at)}</td>
                <td>
                  {bid.status === 'OPEN' && (
                    <button
                      type="button"
                      className={`${ui.button} ${ui.secondary} ${ui.small}`}
                      disabled={withdraw.isPending}
                      onClick={() => {
                        withdraw.mutate(bid);
                      }}
                    >
                      Withdraw
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const ORDER_PILL: Record<string, string> = {
  PENDING: ui.pillWarn ?? '',
  CONFIRMED: ui.pillOk ?? '',
  REJECTED: ui.pillBad ?? '',
};

function MyOrders({ customerId }: { customerId: string }) {
  const [page, setPage] = useState(1);
  const orders = useOrders(customerId, page);
  if (orders.isPending) return <Loading what="your orders" />;
  if (orders.isError) {
    return (
      <ErrorPanel
        error={orders.error}
        title="Could not load your orders"
        onRetry={() => {
          void orders.refetch();
        }}
      />
    );
  }
  if (orders.data.items.length === 0) return <p className={ui.empty}>No orders yet.</p>;
  return (
    <>
      <div className={ui.tableWrap}>
        <table className={ui.table} data-testid="orders-table">
          <caption className="visually-hidden">Your orders, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Item</th>
              <th scope="col" className={ui.num}>
                Price
              </th>
              <th scope="col">Status</th>
              <th scope="col">Time</th>
            </tr>
          </thead>
          <tbody>
            {orders.data.items.map((o) => (
              <tr key={o.order_id}>
                <td>
                  <Link to={`/orders/${o.order_id}`}>{o.order_id.slice(-8)}</Link>
                </td>
                <td>{o.items.map((i) => i.sku.replace('CP-', 'CloudPunk #')).join(', ')}</td>
                <td className={ui.num}>{formatPrice(o.total_amount, o.currency)}</td>
                <td>
                  <span className={`${ui.pill} ${ORDER_PILL[o.status] ?? ''}`}>
                    {o.status.toLowerCase()}
                  </span>
                </td>
                <td>{timeAgo(o.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} size={20} total={orders.data.total} onPage={setPage} />
    </>
  );
}

import { Link } from 'react-router';
import { formatPrice } from './Price';
import { PunkImage } from './PunkImage';
import { Who } from './Who';
import type { ActivityEntry } from '../api/types';
import { numberOf } from '../lib/collection';
import { timeAgo } from '../lib/time';
import ui from '../styles/ui.module.css';

const EVENT: Record<ActivityEntry['kind'], string> = {
  SALE: 'Sale',
  LISTED: 'Up for bid',
  UNLISTED: 'Taken off',
  BID: 'Bid',
  BID_WITHDRAWN: 'Bid withdrawn',
};

/** Sales, listings and bids as a marketplace activity table, newest first. */
export function ActivityTable({
  entries,
  caption,
  showItem = true,
}: {
  entries: readonly ActivityEntry[];
  caption: string;
  showItem?: boolean;
}) {
  if (entries.length === 0) return <p className={ui.empty}>No activity yet.</p>;
  return (
    <div className={ui.tableWrap}>
      <table className={ui.table} data-testid="activity-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Event</th>
            {showItem && <th scope="col">Item</th>}
            <th scope="col" className={ui.num}>
              Price
            </th>
            <th scope="col">From</th>
            <th scope="col">To</th>
            <th scope="col">Time</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const number = numberOf(e.sku);
            const label = number === null ? e.sku : `CloudPunk #${String(number).padStart(4, '0')}`;
            return (
              <tr key={`${e.kind}-${e.sku}-${e.at}-${e.bid_id ?? e.order_id ?? ''}`}>
                <td>
                  <span className={ui.pill}>{EVENT[e.kind]}</span>
                </td>
                {showItem && (
                  <td>
                    <Link to={`/cloudpunks/${e.sku.slice(3)}`} className={ui.lineItem}>
                      <PunkImage sku={e.sku} state={undefined} size="mini" />
                      {label}
                    </Link>
                  </td>
                )}
                <td className={ui.num}>
                  {e.amount && e.currency ? formatPrice(e.amount, e.currency) : '—'}
                </td>
                <td>
                  {e.kind === 'BID' || e.kind === 'BID_WITHDRAWN' ? '—' : <Who id={e.from} />}
                </td>
                <td>{e.to ? <Who id={e.to} /> : '—'}</td>
                <td>
                  <time dateTime={e.at} title={new Date(e.at).toLocaleString()}>
                    {timeAgo(e.at)}
                  </time>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

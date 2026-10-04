import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type SyntheticEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { api } from '../api/endpoints';
import {
  MARKET_KEYS,
  useActiveListing,
  useActivity,
  useBidsFor,
  useCatalog,
  useProduct,
  useStock,
} from '../api/hooks';
import type { Bid, Listing, Order, Stock } from '../api/types';
import { ActivityTable } from '../components/ActivityTable';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { formatPrice } from '../components/Price';
import { PunkImage } from '../components/PunkImage';
import { StatePill } from '../components/StatePill';
import { Who } from '../components/Who';
import {
  parseDescription,
  parseNumber,
  productTraitCounts,
  rarityPercent,
  skuOf,
  stateOf,
  type MarketState,
} from '../lib/collection';
import { clearAttempt, keyFor } from '../lib/idempotency';
import { MoneyParseError, compareDecimal, parseMinor } from '../lib/money';
import { useCustomer } from '../state';
import ui from '../styles/ui.module.css';
import { NotFound } from './NotFound';
import styles from './item.module.css';

/** Refresh everything that decides colours and offers after the market changed. */
function useMarketRefresh() {
  const client = useQueryClient();
  return () => {
    for (const key of MARKET_KEYS) void client.invalidateQueries({ queryKey: [key] });
  };
}

export function ItemPage() {
  const { id = '' } = useParams();
  const number = parseNumber(id);
  if (number === null) return <NotFound />;
  return <Item sku={skuOf(number)} />;
}

function Item({ sku }: { sku: string }) {
  const product = useProduct(sku);
  const stock = useStock(sku);
  const listing = useActiveListing(sku);
  const bids = useBidsFor(sku);
  const catalog = useCatalog();
  const activity = useActivity(1, sku);

  if (product.isPending || stock.isPending || listing.isPending)
    return <Loading what="this CloudPunk" />;
  if (product.isError || stock.isError || listing.isError) {
    return (
      <ErrorPanel
        error={product.error ?? stock.error ?? listing.error}
        title="Could not load this CloudPunk"
        onRetry={() => {
          void product.refetch();
          void stock.refetch();
          void listing.refetch();
        }}
      >
        <Link to="/">Back to the collection</Link>
      </ErrorPanel>
    );
  }

  const p = product.data;
  const state = stateOf(stock.data.available, stock.data.owner, listing.data !== null);
  const { typeName, traits } = parseDescription(p.description);
  const counts = productTraitCounts(catalog.data ?? []);
  const total = catalog.data?.length ?? 0;

  return (
    <div className={styles.page}>
      <div className={styles.left}>
        <div className={styles.media} data-state={state}>
          <PunkImage sku={sku} state={state} size="large" />
        </div>
        <section className={ui.panel} aria-labelledby="traits-heading">
          <h2 id="traits-heading" className={ui.panelTitle}>
            Traits
          </h2>
          <ul className={styles.traits}>
            <li className={styles.trait}>
              <span className={styles.traitKind}>Type</span>
              <span className={styles.traitValue}>{typeName || p.category}</span>
              {total > 0 && (
                <span className={styles.traitRarity}>
                  {rarityPercent(counts.get(`type:${p.category}`) ?? 0, total)} have this
                </span>
              )}
            </li>
            {traits.map((t) => (
              <li key={t} className={styles.trait}>
                <span className={styles.traitKind}>Accessory</span>
                <span className={styles.traitValue}>{t}</span>
                {total > 0 && (
                  <span className={styles.traitRarity}>
                    {rarityPercent(counts.get(t) ?? 0, total)} have this
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className={styles.right}>
        <p className={styles.collectionLink}>
          <Link to="/">CloudPunks</Link>
        </p>
        <h1>{p.name}</h1>
        <p className={styles.ownerLine}>
          <StatePill state={state} />
          <span>
            {stock.data.owner === null ? 'Sold by ' : 'Owned by '}
            <Who id={stock.data.owner} />
          </span>
        </p>

        <PricePanel
          sku={sku}
          name={p.name}
          price={p.price}
          currency={p.currency}
          state={state}
          stock={stock.data}
          listing={listing.data}
          bids={bids.data?.items ?? []}
        />

        <section className={ui.panel} aria-labelledby="offers-heading">
          <h2 id="offers-heading" className={ui.panelTitle}>
            Offers
          </h2>
          {bids.isError ? (
            <ErrorPanel error={bids.error} title="Could not load the offers" />
          ) : (
            <Offers
              sku={sku}
              owner={stock.data.owner}
              listing={listing.data}
              bids={bids.data?.items ?? []}
            />
          )}
        </section>

        <section className={ui.panel} aria-labelledby="item-activity-heading">
          <h2 id="item-activity-heading" className={ui.panelTitle}>
            Item activity
          </h2>
          {activity.isError ? (
            <ErrorPanel error={activity.error} title="Could not load the activity" />
          ) : (
            <ActivityTable
              entries={activity.data?.items ?? []}
              caption={`Activity for ${p.name}`}
              showItem={false}
            />
          )}
        </section>
      </div>
    </div>
  );
}

// -- the price panel: what this viewer can do now ---------------------------------------------

interface PriceProps {
  sku: string;
  name: string;
  price: string;
  currency: string;
  state: MarketState;
  stock: Stock;
  listing: Listing | null;
  bids: readonly Bid[];
}

function topBid(bids: readonly Bid[]): Bid | null {
  const open = bids.filter((b) => b.status === 'OPEN');
  return open.reduce<Bid | null>(
    (best, b) => (best === null || compareDecimal(b.amount, best.amount) > 0 ? b : best),
    null,
  );
}

function PricePanel(props: PriceProps) {
  const { customerId } = useCustomer();
  const mine = props.stock.owner === customerId;
  const best = topBid(props.bids);

  return (
    <section
      className={`${ui.panel} ${styles.pricePanel}`}
      aria-labelledby="price-heading"
      data-testid="price-panel"
    >
      {props.state === 'unsold' && <BuyNow {...props} />}
      {props.state === 'bid' && (
        <>
          <h2 id="price-heading" className={styles.priceLabel}>
            {props.listing?.status === 'SALE_PENDING' ? 'Sale being confirmed' : 'Up for bid'}
          </h2>
          <p className={styles.bigPrice}>
            {best ? formatPrice(best.amount, best.currency) : 'No bids yet'}
          </p>
          {best && (
            <p className={ui.hint}>
              Top bid, by {best.bidder === customerId ? 'you' : best.bidder}
            </p>
          )}
          {mine ? (
            <TakeOff sku={props.sku} pending={props.listing?.status === 'SALE_PENDING'} />
          ) : (
            <MakeOffer {...props} />
          )}
        </>
      )}
      {props.state === 'owned' && (
        <>
          <h2 id="price-heading" className={styles.priceLabel}>
            Not for sale
          </h2>
          {mine ? (
            <PutUp sku={props.sku} />
          ) : (
            <p className={ui.muted}>Only its owner can put it up for bid.</p>
          )}
        </>
      )}
    </section>
  );
}

function BuyNow({ sku, name, price, currency }: PriceProps) {
  const { customerId } = useCustomer();
  const navigate = useNavigate();
  const refresh = useMarketRefresh();
  const [params] = useSearchParams();
  const [confirming, setConfirming] = useState(params.get('buy') === '1');
  const scope = `buy:${sku}`;
  const buy = useMutation({
    mutationFn: (): Promise<Order> =>
      api.createOrder(
        { customer_id: customerId, items: [{ sku, quantity: 1 }] },
        keyFor(scope, customerId),
      ),
    onSuccess: (order) => {
      clearAttempt(scope);
      refresh();
      void navigate(`/orders/${order.order_id}`);
    },
  });

  return (
    <>
      <h2 id="price-heading" className={styles.priceLabel}>
        Current price
      </h2>
      <p className={styles.bigPrice} data-testid="current-price">
        {formatPrice(price, currency)}
      </p>
      {confirming ? (
        <div className={styles.confirm} role="group" aria-label={`Confirm buying ${name}`}>
          <p>
            Buy <strong>{name}</strong> for <strong>{formatPrice(price, currency)}</strong> as{' '}
            <span className={ui.correlation}>{customerId}</span>? This is a demo: nothing is paid.
          </p>
          <div className={ui.row}>
            <button
              type="button"
              className={ui.button}
              disabled={buy.isPending}
              onClick={() => {
                buy.mutate();
              }}
            >
              {buy.isPending ? 'Placing order…' : 'Confirm purchase'}
            </button>
            <button
              type="button"
              className={`${ui.button} ${ui.secondary}`}
              onClick={() => {
                setConfirming(false);
                buy.reset();
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className={`${ui.button} ${ui.wide}`}
          onClick={() => {
            setConfirming(true);
          }}
        >
          Buy now
        </button>
      )}
      {buy.isError && <ErrorPanel error={buy.error} title="Could not buy it" />}
    </>
  );
}

function MakeOffer({ sku, currency }: PriceProps) {
  const { customerId } = useCustomer();
  const refresh = useMarketRefresh();
  const [amount, setAmount] = useState('');
  const [invalid, setInvalid] = useState<string | null>(null);
  const scope = `bid:${sku}`;
  const offer = useMutation({
    mutationFn: (value: string) =>
      api.placeBid(
        { customer_id: customerId, sku, amount: value },
        keyFor(scope, `${customerId}|${value}`),
      ),
    onSuccess: () => {
      clearAttempt(scope);
      setAmount('');
      refresh();
    },
  });

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    const text = amount.trim();
    try {
      if (parseMinor(text) <= 0n) throw new MoneyParseError(text);
    } catch {
      setInvalid('Enter an amount above 0 with at most two decimals, like 25 or 25.50.');
      return;
    }
    setInvalid(null);
    offer.mutate(text);
  };

  return (
    <form onSubmit={submit} className={styles.offer} noValidate>
      <div className={ui.field}>
        <label htmlFor="offer-amount">Your offer ({currency})</label>
        <input
          id="offer-amount"
          className={ui.input}
          inputMode="decimal"
          autoComplete="off"
          value={amount}
          aria-invalid={invalid !== null}
          aria-describedby={invalid ? 'offer-error' : undefined}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
        />
        {invalid && (
          <p id="offer-error" className={ui.fieldError}>
            {invalid}
          </p>
        )}
      </div>
      <button type="submit" className={`${ui.button} ${ui.wide}`} disabled={offer.isPending}>
        {offer.isPending ? 'Placing offer…' : 'Make offer'}
      </button>
      {offer.isSuccess && (
        <p role="status" className={`${ui.alert} ${ui.alertOk}`}>
          Offer placed. The owner can accept it.
        </p>
      )}
      {offer.isError && <ErrorPanel error={offer.error} title="Could not place the offer" />}
    </form>
  );
}

function PutUp({ sku }: { sku: string }) {
  const { customerId } = useCustomer();
  const refresh = useMarketRefresh();
  const putUp = useMutation({
    mutationFn: () => api.putUp(customerId, sku),
    onSuccess: refresh,
  });
  return (
    <>
      <p className={ui.muted}>
        It is yours. Put it up and others can bid on it; you choose the bid to accept.
      </p>
      <button
        type="button"
        className={`${ui.button} ${ui.wide}`}
        disabled={putUp.isPending}
        onClick={() => {
          putUp.mutate();
        }}
      >
        Put up for bid
      </button>
      {putUp.isError && <ErrorPanel error={putUp.error} title="Could not put it up for bid" />}
    </>
  );
}

function TakeOff({ sku, pending }: { sku: string; pending: boolean }) {
  const { customerId } = useCustomer();
  const refresh = useMarketRefresh();
  const takeOff = useMutation({
    mutationFn: () => api.takeOff(customerId, sku),
    onSuccess: refresh,
  });
  if (pending) {
    return (
      <p className={ui.muted}>
        You accepted a bid. It changes hands as soon as the sale is confirmed.
      </p>
    );
  }
  return (
    <>
      <p className={ui.muted}>
        It is yours and up for bid. Accept an offer below, or take it off the market.
      </p>
      <button
        type="button"
        className={`${ui.button} ${ui.secondary} ${ui.wide}`}
        disabled={takeOff.isPending}
        onClick={() => {
          takeOff.mutate();
        }}
      >
        Take off the market
      </button>
      {takeOff.isError && (
        <ErrorPanel error={takeOff.error} title="Could not take it off the market" />
      )}
    </>
  );
}

// -- offers -----------------------------------------------------------------------------------

const BID_PILL: Record<string, string> = {
  OPEN: ui.pillOk ?? '',
  ACCEPTED: ui.pillWarn ?? '',
  FILLED: ui.pillOk ?? '',
  FAILED: ui.pillBad ?? '',
};

function Offers({
  sku,
  owner,
  listing,
  bids,
}: {
  sku: string;
  owner: string | null;
  listing: Listing | null;
  bids: readonly Bid[];
}) {
  const { customerId } = useCustomer();
  const refresh = useMarketRefresh();
  const [accepted, setAccepted] = useState<Order | null>(null);
  const accept = useMutation({
    mutationFn: (bid: Bid) => api.acceptBid(bid.bid_id, customerId),
    onSuccess: (order) => {
      setAccepted(order);
      refresh();
    },
  });
  const withdraw = useMutation({
    mutationFn: (bid: Bid) => api.withdrawBid(bid.bid_id, customerId),
    onSuccess: refresh,
  });

  if (bids.length === 0) return <p className={ui.empty}>No offers yet.</p>;
  const canAccept = owner === customerId && listing?.status === 'OPEN';

  return (
    <>
      {accepted && (
        <p role="status" className={`${ui.alert} ${ui.alertOk}`}>
          Bid accepted. {sku.replace('CP-', 'CloudPunk #')} changes hands as soon as the sale is
          confirmed. <Link to={`/orders/${accepted.order_id}`}>Follow the sale</Link>
        </p>
      )}
      {accept.isError && <ErrorPanel error={accept.error} title="Could not accept the bid" />}
      {withdraw.isError && <ErrorPanel error={withdraw.error} title="Could not withdraw the bid" />}
      <div className={ui.tableWrap}>
        <table className={ui.table} data-testid="offers-table">
          <caption className="visually-hidden">Offers on this CloudPunk, newest first</caption>
          <thead>
            <tr>
              <th scope="col" className={ui.num}>
                Price
              </th>
              <th scope="col">From</th>
              <th scope="col">Status</th>
              <th scope="col">
                <span className="visually-hidden">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {bids.map((bid) => (
              <tr key={bid.bid_id}>
                <td className={ui.num}>{formatPrice(bid.amount, bid.currency)}</td>
                <td>
                  <Who id={bid.bidder} />
                </td>
                <td>
                  <span className={`${ui.pill} ${BID_PILL[bid.status] ?? ''}`}>
                    {bid.status.toLowerCase()}
                  </span>
                </td>
                <td>
                  {bid.status === 'OPEN' && canAccept && (
                    <button
                      type="button"
                      aria-label={`Accept ${formatPrice(bid.amount, bid.currency)}`}
                      className={`${ui.button} ${ui.small}`}
                      disabled={accept.isPending}
                      onClick={() => {
                        accept.mutate(bid);
                      }}
                    >
                      Accept
                    </button>
                  )}
                  {bid.status === 'OPEN' && bid.bidder === customerId && (
                    <button
                      type="button"
                      aria-label={`Withdraw ${formatPrice(bid.amount, bid.currency)}`}
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

import { useMemo, useState } from 'react';
import { NavLink, useSearchParams } from 'react-router';
import { useActivity, useCategories, useCollection } from '../api/hooks';
import { ActivityTable } from '../components/ActivityTable';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { Pagination } from '../components/Pagination';
import { formatPrice } from '../components/Price';
import { PunkCard } from '../components/PunkCard';
import { PunkImage } from '../components/PunkImage';
import { StateLegend } from '../components/StatePill';
import {
  SORT_LABEL,
  STATE_LABEL,
  activeFilterCount,
  COLLECTION_FACE,
  applyFilters,
  collectionStats,
  filtersFromSearch,
  searchFromFilters,
  sortPunks,
  traitCounts,
  type CloudPunk,
  type Filters,
  type MarketState,
  type SortKey,
} from '../lib/collection';
import styles from './collection.module.css';
import ui from '../styles/ui.module.css';

/** The collection page: header, then the Items tab (filters and grid) or the Activity tab. */
export function CollectionPage({ tab }: { tab: 'items' | 'activity' }) {
  const collection = useCollection();

  return (
    <>
      <CollectionHeader punks={collection.punks} />
      <nav aria-label="Collection" className={ui.tabs}>
        <NavLink to="/" end>
          Items
        </NavLink>
        <NavLink to="/activity">Activity</NavLink>
      </nav>
      {tab === 'items' ? <Items collection={collection} /> : <Activity />}
    </>
  );
}

function CollectionHeader({ punks }: { punks: CloudPunk[] | undefined }) {
  const stats = punks ? collectionStats(punks) : null;
  const [more, setMore] = useState(false);
  return (
    <section className={styles.hero} aria-labelledby="collection-name">
      <div className={styles.banner} aria-hidden="true" data-testid="banner">
        {(punks ?? []).slice(0, 54).map((p) => (
          <PunkImage key={p.sku} sku={p.sku} state={p.state} size="card" />
        ))}
      </div>
      <div className={styles.identity}>
        <div className={styles.avatar}>
          <PunkImage sku={COLLECTION_FACE} state="unsold" size="card" />
        </div>
        <div>
          <h1 id="collection-name">CloudPunks</h1>
          <p className={styles.byline}>
            By <strong>CloudPunks</strong> · 100 items · Priced in ETH
          </p>
        </div>
      </div>
      <p className={styles.description}>
        100 one-of-a-kind 24×24 pixel characters. An unsold CloudPunk is red and can be bought from
        CloudPunks at its price; once bought it turns blue. Its owner can put it up for bid, which
        turns it purple, and accept the bid they like.
        {more && (
          <>
            {' '}
            There is no blockchain and no payment: a sale is an order, and your customer id plays
            the part of a wallet address.
          </>
        )}{' '}
        <button
          type="button"
          className={styles.more}
          aria-expanded={more}
          onClick={() => {
            setMore(!more);
          }}
        >
          {more ? 'Show less' : 'See more'}
        </button>
      </p>
      <dl className={styles.stats} data-testid="collection-stats">
        <div>
          <dt>Floor price</dt>
          <dd>{stats?.floor ? formatPrice(stats.floor.amount, stats.floor.currency) : '—'}</dd>
        </div>
        <div>
          <dt>Items</dt>
          <dd>{stats?.items ?? '—'}</dd>
        </div>
        <div>
          <dt>Owners</dt>
          <dd>{stats?.owners ?? '—'}</dd>
        </div>
        <div>
          <dt>Unsold</dt>
          <dd>{stats?.unsold ?? '—'}</dd>
        </div>
        <div>
          <dt>Up for bid</dt>
          <dd>{stats?.upForBid ?? '—'}</dd>
        </div>
      </dl>
    </section>
  );
}

// -- the Items tab ----------------------------------------------------------------------------

function toggle<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function Items({ collection }: { collection: ReturnType<typeof useCollection> }) {
  const [params, setParams] = useSearchParams();
  const filters = filtersFromSearch(params);
  const categories = useCategories();
  const [query, setQuery] = useState(filters.q);

  const update = (next: Partial<Filters>) => {
    setParams(searchFromFilters({ ...filters, ...next }), { replace: true });
  };

  const punks = collection.punks;
  const counts = useMemo(() => traitCounts(punks ?? []), [punks]);
  const shown = useMemo(
    () => (punks ? sortPunks(applyFilters(punks, filters), filters.sort, counts) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- filters is rebuilt from params
    [punks, params, counts],
  );

  if (collection.isPending) return <Loading what="the collection" />;
  if (collection.error) {
    return (
      <ErrorPanel
        error={collection.error}
        title="Could not load the collection"
        onRetry={collection.refetch}
      />
    );
  }
  const all = punks ?? [];
  const traitNames = [...counts.keys()].filter((k) => !k.startsWith('type:')).sort();
  const attributeCounts = [...new Set(all.map((p) => p.traits.length))].sort((a, b) => a - b);
  const stateCount = (s: MarketState) => all.filter((p) => p.state === s).length;
  const active = activeFilterCount(filters);

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar} aria-label="Filters">
        <details open className={styles.group}>
          <summary>Status</summary>
          <fieldset>
            <legend className="visually-hidden">Status</legend>
            {(['unsold', 'bid', 'owned'] as const).map((state) => (
              <label key={state} className={styles.option} data-state={state}>
                <input
                  type="checkbox"
                  checked={filters.status.includes(state)}
                  onChange={() => {
                    update({ status: toggle(filters.status, state) });
                  }}
                />
                <span className={styles.swatch} aria-hidden="true" />
                {state === 'unsold' ? 'Buy now' : STATE_LABEL[state]}
                <span className={styles.count}>{stateCount(state)}</span>
              </label>
            ))}
          </fieldset>
        </details>
        <details open className={styles.group}>
          <summary>Type</summary>
          <fieldset>
            <legend className="visually-hidden">Type</legend>
            {(categories.data?.items ?? []).map((c) => (
              <label key={c.slug} className={styles.option}>
                <input
                  type="checkbox"
                  checked={filters.types.includes(c.slug)}
                  onChange={() => {
                    update({ types: toggle(filters.types, c.slug) });
                  }}
                />
                {c.name}
                <span className={styles.count}>{counts.get(`type:${c.slug}`) ?? 0}</span>
              </label>
            ))}
          </fieldset>
        </details>
        <details className={styles.group}>
          <summary>Accessories</summary>
          <fieldset className={styles.scroll}>
            <legend className="visually-hidden">Accessories</legend>
            {traitNames.map((trait) => (
              <label key={trait} className={styles.option}>
                <input
                  type="checkbox"
                  checked={filters.traits.includes(trait)}
                  onChange={() => {
                    update({ traits: toggle(filters.traits, trait) });
                  }}
                />
                {trait}
                <span className={styles.count}>{counts.get(trait) ?? 0}</span>
              </label>
            ))}
          </fieldset>
        </details>
        <details className={styles.group}>
          <summary>Attribute count</summary>
          <fieldset>
            <legend className="visually-hidden">Attribute count</legend>
            {attributeCounts.map((n) => (
              <label key={n} className={styles.option}>
                <input
                  type="checkbox"
                  checked={filters.counts.includes(n)}
                  onChange={() => {
                    update({ counts: toggle(filters.counts, n) });
                  }}
                />
                {n} attributes
                <span className={styles.count}>
                  {all.filter((p) => p.traits.length === n).length}
                </span>
              </label>
            ))}
          </fieldset>
        </details>
      </aside>

      <section aria-label="Items">
        <div className={styles.toolbar}>
          <form
            role="search"
            className={styles.find}
            onSubmit={(e) => {
              e.preventDefault();
              update({ q: query.trim() });
            }}
          >
            <label htmlFor="item-search" className="visually-hidden">
              Search the collection
            </label>
            <input
              id="item-search"
              type="search"
              className={ui.input}
              placeholder="Search by number or trait"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                if (e.target.value === '') update({ q: '' });
              }}
            />
          </form>
          {/* Only the count: the background refresh every 10 s stays invisible, so this line never
              shifts or re-announces itself when nothing changed. */}
          <p className={styles.results} aria-live="polite" data-testid="result-count">
            {shown.length} {shown.length === 1 ? 'item' : 'items'}
          </p>
          <label htmlFor="sort" className="visually-hidden">
            Sort by
          </label>
          <select
            id="sort"
            className={ui.select}
            value={filters.sort}
            onChange={(e) => {
              update({ sort: e.target.value as SortKey });
            }}
          >
            {(Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
              <option key={key} value={key}>
                {SORT_LABEL[key]}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.legendRow}>
          <StateLegend />
          {active > 0 && (
            <button
              type="button"
              className={`${ui.button} ${ui.secondary} ${ui.small}`}
              onClick={() => {
                setQuery('');
                setParams(filters.sort === 'price-asc' ? {} : { sort: filters.sort }, {
                  replace: true,
                });
              }}
            >
              Clear all filters ({active})
            </button>
          )}
        </div>
        {shown.length === 0 ? (
          <p className={ui.empty}>No CloudPunks match these filters.</p>
        ) : (
          <ul className={styles.grid} aria-label="CloudPunks">
            {shown.map((punk) => (
              <PunkCard key={punk.sku} punk={punk} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// -- the Activity tab -------------------------------------------------------------------------

function Activity() {
  const [page, setPage] = useState(1);
  const activity = useActivity(page);
  if (activity.isPending) return <Loading what="the activity" />;
  if (activity.isError) {
    return (
      <ErrorPanel
        error={activity.error}
        title="Could not load the activity"
        onRetry={() => {
          void activity.refetch();
        }}
      />
    );
  }
  return (
    <section aria-labelledby="activity-heading">
      <h2 id="activity-heading" className="visually-hidden">
        Activity
      </h2>
      <ActivityTable
        entries={activity.data.items}
        caption="Sales, listings and bids, newest first"
      />
      <Pagination page={page} size={20} total={activity.data.total} onPage={setPage} />
    </section>
  );
}

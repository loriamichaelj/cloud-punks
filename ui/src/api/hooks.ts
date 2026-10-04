// Server state (TanStack Query). The one hard rule lives here: STOCK IS NEVER CACHED, and neither
// is anything that decides a CloudPunk's colour (its owner, its listing, its bids). Those queries
// use staleTime 0 and gcTime 0, refetch on mount and on focus, and are never persisted. Catalog
// data (names, descriptions, mint prices) may sit in memory for up to 60 s.

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { buildCollection, numberOf, type CloudPunk } from '../lib/collection';
import { GIVE_UP_MS, isTerminal, nextPollDelay } from '../lib/polling';
import { api } from './endpoints';
import type { ActivityEntry, Product } from './types';

export const CATALOG_STALE_MS = 60_000;
/** The collection grid refreshes this often while the tab is visible (DESIGN.md 16.6). */
export const MARKET_REFRESH_MS = 10_000;
/** An item page watches its CloudPunk more closely: a sale settles within seconds. */
export const ITEM_REFRESH_MS = 3_000;
const AVAILABILITY_BATCH = 20; // the availability endpoint's cap
const COLLECTION_SIZE = 100;

const liveOptions = {
  staleTime: 0,
  gcTime: 0,
  refetchOnMount: 'always',
  refetchOnWindowFocus: true,
  retry: false,
} as const;

/** Poll every ``ms`` while the query is healthy. While it is failing, wait for "Try again" (or
 * window focus) instead of failing, and redrawing the error, every few seconds. */
function whileHealthy(ms: number) {
  return (query: { state: { status: string } }) => (query.state.status === 'error' ? false : ms);
}

const catalogOptions = { staleTime: CATALOG_STALE_MS, retry: false } as const;

export const MARKET_KEYS = ['market', 'stock', 'listings', 'bids', 'activity', 'orders'] as const;

export function useCategories() {
  return useQuery({
    queryKey: ['categories'],
    queryFn: ({ signal }) => api.categories({ signal }),
    ...catalogOptions,
  });
}

/** Every product in one page (the collection is 100), only the CloudPunks kept. */
export function useCatalog() {
  return useQuery({
    queryKey: ['catalog'],
    queryFn: async ({ signal }): Promise<Product[]> => {
      const page = await api.products({ size: COLLECTION_SIZE }, { signal });
      return page.items.filter((p) => numberOf(p.sku) !== null);
    },
    ...catalogOptions,
  });
}

interface MarketSnapshot {
  stock: Map<string, { available: number; owner: string | null }>;
  listed: Set<string>;
  lastSales: Map<string, { amount: string; currency: string }>;
}

/** Inventory for every CloudPunk (in batches of 20), the active listings and the recent sales. */
export function useMarket(skus: readonly string[]) {
  const key = skus.join(',');
  return useQuery({
    queryKey: ['market', key],
    queryFn: async ({ signal }): Promise<MarketSnapshot> => {
      const batches: string[][] = [];
      for (let i = 0; i < skus.length; i += AVAILABILITY_BATCH) {
        batches.push(skus.slice(i, i + AVAILABILITY_BATCH));
      }
      const [lines, listings, activity] = await Promise.all([
        Promise.all(
          batches.map((batch) =>
            api.availability(
              batch.map((sku) => ({ sku, quantity: 1 })),
              { signal },
            ),
          ),
        ),
        api.listings({ status: 'ACTIVE', size: COLLECTION_SIZE }, { signal }),
        api.activity({ size: COLLECTION_SIZE }, { signal }),
      ]);
      const stock = new Map<string, { available: number; owner: string | null }>();
      for (const report of lines) {
        for (const line of report.items) {
          stock.set(line.sku, { available: line.available, owner: line.owner });
        }
      }
      const lastSales = new Map<string, { amount: string; currency: string }>();
      for (const entry of activity.items) {
        // newest first, so the first sale seen for an SKU is its latest
        if (entry.kind === 'SALE' && entry.amount && entry.currency && !lastSales.has(entry.sku)) {
          lastSales.set(entry.sku, { amount: entry.amount, currency: entry.currency });
        }
      }
      return { stock, listed: new Set(listings.items.map((l) => l.sku)), lastSales };
    },
    enabled: skus.length > 0,
    refetchInterval: whileHealthy(MARKET_REFRESH_MS),
    ...liveOptions,
  });
}

/** The collection as the screens see it: catalog plus live market state. */
export function useCollection() {
  const catalog = useCatalog();
  const skus = useMemo(() => (catalog.data ?? []).map((p) => p.sku), [catalog.data]);
  const market = useMarket(skus);
  const punks = useMemo<CloudPunk[] | undefined>(
    () => (catalog.data && market.data ? buildCollection(catalog.data, market.data) : undefined),
    [catalog.data, market.data],
  );
  return {
    punks,
    isPending: catalog.isPending || (skus.length > 0 && market.isPending),
    error: catalog.error ?? market.error,
    refetch: () => {
      void catalog.refetch();
      void market.refetch();
    },
  };
}

export function useProduct(sku: string) {
  return useQuery({
    queryKey: ['product', sku],
    queryFn: ({ signal }) => api.product(sku, { signal }),
    ...catalogOptions,
  });
}

export function useStock(sku: string) {
  return useQuery({
    queryKey: ['stock', sku],
    queryFn: ({ signal }) => api.stock(sku, { signal }),
    refetchInterval: whileHealthy(ITEM_REFRESH_MS),
    ...liveOptions,
  });
}

/** The CloudPunk's active listing, or null when it is not up for bid. */
export function useActiveListing(sku: string) {
  return useQuery({
    queryKey: ['listings', sku],
    queryFn: async ({ signal }) => {
      const page = await api.listings({ sku, status: 'ACTIVE' }, { signal });
      return page.items[0] ?? null;
    },
    refetchInterval: whileHealthy(ITEM_REFRESH_MS),
    ...liveOptions,
  });
}

export function useBidsFor(sku: string) {
  return useQuery({
    queryKey: ['bids', 'sku', sku],
    queryFn: ({ signal }) => api.bids({ sku, size: 100 }, { signal }),
    refetchInterval: whileHealthy(ITEM_REFRESH_MS),
    ...liveOptions,
  });
}

export function useMyBids(customerId: string) {
  return useQuery({
    queryKey: ['bids', 'customer', customerId],
    queryFn: ({ signal }) => api.bids({ customerId, size: 100 }, { signal }),
    ...liveOptions,
  });
}

/** The activity feed, newest first; for one CloudPunk with ``sku``. Only CloudPunks are shown. */
export function useActivity(page: number, sku?: string) {
  return useQuery({
    queryKey: ['activity', sku ?? null, page],
    queryFn: async ({ signal }) => {
      const result = await api.activity(
        { page, size: 20, ...(sku === undefined ? {} : { sku }) },
        { signal },
      );
      const items: ActivityEntry[] = result.items.filter((e) => numberOf(e.sku) !== null);
      return { ...result, items };
    },
    placeholderData: keepPreviousData,
    refetchInterval: whileHealthy(sku === undefined ? MARKET_REFRESH_MS : ITEM_REFRESH_MS),
    ...liveOptions,
  });
}

/** Elapsed milliseconds since the first render of the calling component. */
function useElapsedSince(): () => number {
  const [start] = useState(() => Date.now());
  return () => Date.now() - start;
}

export function useOrder(id: string) {
  const elapsed = useElapsedSince();
  return useQuery({
    queryKey: ['order', id],
    queryFn: ({ signal }) => api.order(id, { signal }),
    // 1 s for 10 s, then 2 s; stop at a terminal status or after 60 s. Polling pauses while the
    // tab is hidden (refetchIntervalInBackground defaults to false).
    refetchInterval: (query) => nextPollDelay(elapsed(), query.state.data?.status),
    staleTime: 0,
    retry: false,
  });
}

/** True once an order has been watched for the give-up window while still PENDING. */
export function useGaveUp(status: string | undefined): boolean {
  const [gaveUp, setGaveUp] = useState(false);
  useEffect(() => {
    if (status === undefined || isTerminal(status)) return;
    const timer = setTimeout(() => {
      setGaveUp(true);
    }, GIVE_UP_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [status]);
  return gaveUp && status !== undefined && !isTerminal(status);
}

export function useNotifications(orderId: string, orderStatus: string | undefined) {
  const elapsed = useElapsedSince();
  return useQuery({
    queryKey: ['notifications', orderId],
    queryFn: ({ signal }) => api.notifications(orderId, { signal }),
    // Notifications follow the order a moment later, so keep looking until the status
    // notification has arrived (or the give-up window ends).
    refetchInterval: (query) => {
      const types = query.state.data?.items.map((n) => n.type) ?? [];
      const done =
        orderStatus !== undefined &&
        isTerminal(orderStatus) &&
        types.includes('OrderStatusUpdated');
      return done ? false : nextPollDelay(elapsed(), undefined);
    },
    staleTime: 0,
    retry: false,
  });
}

export function useOrders(customerId: string, page: number) {
  return useQuery({
    queryKey: ['orders', customerId, page],
    queryFn: ({ signal }) => api.orders({ customerId, page, size: 20 }, { signal }),
    placeholderData: keepPreviousData,
    staleTime: 0,
    retry: false,
  });
}

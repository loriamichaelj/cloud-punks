// Server state (TanStack Query). The one hard rule lives here: STOCK IS NEVER CACHED. Inventory
// queries use staleTime 0 and gcTime 0, refetch on mount and on focus, and are never persisted.
// Catalog data may sit in memory for up to 60 s (the server tolerates 5 minutes).

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { GIVE_UP_MS, isTerminal, nextPollDelay } from '../lib/polling';
import { api } from './endpoints';

export const CATALOG_STALE_MS = 60_000;

const stockOptions = {
  staleTime: 0,
  gcTime: 0,
  refetchOnMount: 'always',
  refetchOnWindowFocus: true,
  retry: false,
} as const;

const catalogOptions = { staleTime: CATALOG_STALE_MS, retry: false } as const;

export function useCategories() {
  return useQuery({
    queryKey: ['categories'],
    queryFn: ({ signal }) => api.categories({ signal }),
    ...catalogOptions,
  });
}

export function useProducts(category: string | undefined, page: number) {
  return useQuery({
    queryKey: ['products', { category: category ?? null, page }],
    queryFn: ({ signal }) =>
      api.products({ ...(category ? { category } : {}), page, size: 20 }, { signal }),
    placeholderData: keepPreviousData,
    ...catalogOptions,
  });
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
    ...stockOptions,
  });
}

/** Availability of one unit of each SKU (the catalog page) or of the basket's quantities. */
export function useAvailability(items: { sku: string; quantity: number }[]) {
  const key = items.map((i) => `${i.sku}x${i.quantity}`).join(',');
  return useQuery({
    queryKey: ['availability', key],
    queryFn: ({ signal }) => api.availability(items, { signal }),
    enabled: items.length > 0,
    ...stockOptions,
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

// One typed function per endpoint the UI uses. No React in here.

import { request, type RequestOptions } from './client';
import type {
  ActivityPage,
  Availability,
  Bid,
  BidPage,
  CategoryList,
  Listing,
  ListingPage,
  NotificationList,
  Order,
  OrderCreate,
  OrderPage,
  Product,
  ProductPage,
  Stock,
} from './types';

type Opts = Pick<RequestOptions, 'signal' | 'correlationId'>;

const q = (params: Record<string, string | number | undefined>): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
};

const path = encodeURIComponent;

export const api = {
  categories: (o: Opts = {}) => request<CategoryList>('/categories', o),

  products: (p: { category?: string; page?: number; size?: number }, o: Opts = {}) =>
    request<ProductPage>(`/products${q(p)}`, o),

  product: (sku: string, o: Opts = {}) => request<Product>(`/products/${path(sku)}`, o),

  stock: (sku: string, o: Opts = {}) => request<Stock>(`/inventory/${path(sku)}`, o),

  availability: (items: { sku: string; quantity: number }[], o: Opts = {}) =>
    request<Availability>('/inventory/availability', { ...o, method: 'POST', body: { items } }),

  createOrder: (
    body: OrderCreate,
    idempotencyKey: string,
    o: Opts & { sleep?: (ms: number) => Promise<void> } = {},
  ) =>
    request<Order>('/orders', {
      ...o,
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': idempotencyKey },
      retry503: 3, // safe: the same key makes a repeat a replay, never a second order
    }),

  order: (id: string, o: Opts = {}) => request<Order>(`/orders/${path(id)}`, o),

  orders: (p: { customerId: string; page?: number; size?: number }, o: Opts = {}) =>
    request<OrderPage>(`/orders${q({ customer_id: p.customerId, page: p.page, size: p.size })}`, o),

  notifications: (orderId: string, o: Opts = {}) =>
    request<NotificationList>(`/notifications${q({ order_id: orderId })}`, o),

  // -- the market ---------------------------------------------------------------------------

  listings: (p: { sku?: string; status?: string; page?: number; size?: number }, o: Opts = {}) =>
    request<ListingPage>(`/listings${q(p)}`, o),

  putUp: (customerId: string, sku: string, o: Opts = {}) =>
    request<Listing>('/listings', { ...o, method: 'POST', body: { customer_id: customerId, sku } }),

  takeOff: (customerId: string, sku: string, o: Opts = {}) =>
    request<Listing>(`/listings/${path(sku)}${q({ customer_id: customerId })}`, {
      ...o,
      method: 'DELETE',
    }),

  bids: (
    p: { sku?: string; customerId?: string; status?: string; page?: number; size?: number },
    o: Opts = {},
  ) =>
    request<BidPage>(
      `/bids${q({ sku: p.sku, customer_id: p.customerId, status: p.status, page: p.page, size: p.size })}`,
      o,
    ),

  placeBid: (
    body: { customer_id: string; sku: string; amount: string },
    idempotencyKey: string,
    o: Opts = {},
  ) =>
    request<Bid>('/bids', {
      ...o,
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': idempotencyKey },
      retry503: 3, // the same key makes a repeat a replay, never a second bid
    }),

  withdrawBid: (bidId: string, customerId: string, o: Opts = {}) =>
    request<Bid>(`/bids/${path(bidId)}${q({ customer_id: customerId })}`, {
      ...o,
      method: 'DELETE',
    }),

  acceptBid: (bidId: string, customerId: string, o: Opts = {}) =>
    request<Order>(`/bids/${path(bidId)}/accept`, {
      ...o,
      method: 'POST',
      body: { customer_id: customerId },
      retry503: 3, // accepting the same bid again returns the same order
    }),

  activity: (p: { sku?: string; page?: number; size?: number }, o: Opts = {}) =>
    request<ActivityPage>(`/activity${q(p)}`, o),
};

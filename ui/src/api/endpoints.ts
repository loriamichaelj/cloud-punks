// One typed function per endpoint the UI uses. No React in here.

import { request, type RequestOptions } from './client';
import type {
  Availability,
  CategoryList,
  NotificationList,
  Order,
  OrderCreate,
  OrderPage,
  Product,
  ProductPage,
  ProductUpdate,
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

export const api = {
  categories: (o: Opts = {}) => request<CategoryList>('/categories', o),

  products: (p: { category?: string; page?: number; size?: number }, o: Opts = {}) =>
    request<ProductPage>(`/products${q(p)}`, o),

  product: (sku: string, o: Opts = {}) =>
    request<Product>(`/products/${encodeURIComponent(sku)}`, o),

  updateProduct: (sku: string, body: ProductUpdate, o: Opts = {}) =>
    request<Product>(`/products/${encodeURIComponent(sku)}`, { ...o, method: 'PUT', body }),

  stock: (sku: string, o: Opts = {}) => request<Stock>(`/inventory/${encodeURIComponent(sku)}`, o),

  setStock: (sku: string, available: number, o: Opts = {}) =>
    request<Stock>(`/inventory/${encodeURIComponent(sku)}`, {
      ...o,
      method: 'PUT',
      body: { available },
    }),

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

  order: (id: string, o: Opts = {}) => request<Order>(`/orders/${encodeURIComponent(id)}`, o),

  orders: (p: { customerId: string; page?: number; size?: number }, o: Opts = {}) =>
    request<OrderPage>(`/orders${q({ customer_id: p.customerId, page: p.page, size: p.size })}`, o),

  notifications: (orderId: string, o: Opts = {}) =>
    request<NotificationList>(`/notifications${q({ order_id: orderId })}`, o),
};

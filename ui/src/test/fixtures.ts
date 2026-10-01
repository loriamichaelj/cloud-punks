import type { Notification, Order, Product } from '../api/types';

export function product(sku: string, over: Partial<Product> = {}): Product {
  return {
    sku,
    name: `Product ${sku}`,
    description: 'A fine product.',
    category: 'apparel',
    price: '19.99',
    currency: 'USD',
    active: true,
    created_at: '2026-10-01T12:00:00Z',
    updated_at: '2026-10-01T12:00:00Z',
    ...over,
  };
}

export function order(over: Partial<Order> = {}): Order {
  return {
    order_id: '01J9Z6R0C4AAAAAAAAAAAAAAAA',
    customer_id: 'cust-test',
    status: 'PENDING',
    status_reason: null,
    total_amount: '39.98',
    currency: 'USD',
    items: [{ sku: 'SKU-A', quantity: 2, unit_price: '19.99' }],
    created_at: '2026-10-01T12:00:00Z',
    updated_at: '2026-10-01T12:00:00Z',
    ...over,
  };
}

export function note(type: string, message: string, id: string): Notification {
  return {
    event_id: id,
    type,
    channel: 'email',
    message,
    created_at: '2026-10-01T12:00:01Z',
  };
}

export function apiError(code: string, message: string, correlationId = 'corr-from-server') {
  return { error: { code, message, correlation_id: correlationId } };
}

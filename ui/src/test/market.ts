// An in-memory CloudPunks market behind MSW, for the component tests: the products, inventory,
// listings, bids, activity and orders the screens read, with the API's rules for the writes the
// screens make. Every request is recorded so a test can check what was sent.

import { http, HttpResponse } from 'msw';
import type { ActivityEntry, Bid, Listing, Order, Product } from '../api/types';
import { apiError } from './fixtures';

export const ME = 'cust-me';
export const NOW = '2026-10-04T12:00:00Z';

export interface Recorded {
  method: string;
  path: string;
  search: URLSearchParams;
  headers: Headers;
  body: unknown;
}

interface StockRow {
  available: number;
  owner: string | null;
}

export interface Market {
  products: Product[];
  stock: Map<string, StockRow>;
  listings: Listing[];
  bids: Bid[];
  activity: ActivityEntry[];
  orders: Order[];
  requests: Recorded[];
  /** Answer the next request to this path with this error once (e.g. a 503 or a 409). */
  failNext: Map<string, { status: number; code: string; message: string }>;
}

let ids = 0;
const ulid = (prefix: string) => `${prefix}${String(++ids).padStart(26 - prefix.length, '0')}`;

export function cloudPunk(
  n: number,
  description: string,
  price: string,
  category = 'male',
): Product {
  const number = String(n).padStart(4, '0');
  return {
    sku: `CP-${number}`,
    name: `CloudPunk #${number}`,
    description,
    category,
    price,
    currency: 'ETH',
    active: true,
    created_at: NOW,
    updated_at: NOW,
  };
}

/** Four CloudPunks: #1 and #4 unsold (red), #2 owned by ME (blue), #3 up for bid by Bob (purple). */
export function newMarket(): Market {
  const market: Market = {
    products: [
      cloudPunk(1, 'Male · Mohawk Thin, Classic Shades, Cigarette, Earring', '31.43'),
      cloudPunk(2, 'Female · Pigtails, Hot Lipstick', '9.50', 'female'),
      cloudPunk(3, 'Male · Cap, Earring', '20.00'),
      cloudPunk(4, 'Zombie · Cap, Pipe, Earring', '75.00', 'zombie'),
    ],
    stock: new Map([
      ['CP-0001', { available: 1, owner: null }],
      ['CP-0002', { available: 0, owner: ME }],
      ['CP-0003', { available: 0, owner: 'cust-bob' }],
      ['CP-0004', { available: 1, owner: null }],
    ]),
    listings: [],
    bids: [],
    activity: [
      {
        kind: 'SALE',
        sku: 'CP-0002',
        at: NOW,
        amount: '9.50',
        currency: 'ETH',
        from: null,
        to: ME,
        order_id: ulid('01ORD'),
        bid_id: null,
      },
    ],
    orders: [],
    requests: [],
    failNext: new Map(),
  };
  putUp(market, 'CP-0003', 'cust-bob');
  return market;
}

export function putUp(market: Market, sku: string, seller: string): Listing {
  const listing: Listing = {
    listing_id: ulid('01LST'),
    sku,
    seller,
    status: 'OPEN',
    created_at: NOW,
    updated_at: NOW,
  };
  market.listings.push(listing);
  return listing;
}

export function addBid(market: Market, sku: string, bidder: string, amount: string): Bid {
  const listing = market.listings.find((l) => l.sku === sku && l.status === 'OPEN');
  if (!listing) throw new Error(`${sku} is not listed`);
  const bid: Bid = {
    bid_id: ulid('01BID'),
    listing_id: listing.listing_id,
    sku,
    bidder,
    amount,
    currency: 'ETH',
    status: 'OPEN',
    order_id: null,
    created_at: NOW,
    updated_at: NOW,
  };
  market.bids.unshift(bid);
  return bid;
}

const page = <T>(items: T[], search: URLSearchParams) => {
  const size = Number(search.get('size') ?? '20');
  const p = Number(search.get('page') ?? '1');
  return { items: items.slice((p - 1) * size, p * size), page: p, size, total: items.length };
};

const active = (l: Listing) => l.status === 'OPEN' || l.status === 'SALE_PENDING';

export function marketHandlers(market: Market) {
  const record = async (request: Request) => {
    const url = new URL(request.url);
    let body: unknown = undefined;
    try {
      body = await request.clone().json();
    } catch {
      // no JSON body
    }
    market.requests.push({
      method: request.method,
      path: url.pathname,
      search: url.searchParams,
      headers: request.headers,
      body,
    });
    const failure = market.failNext.get(`${request.method} ${url.pathname}`);
    if (failure) {
      market.failNext.delete(`${request.method} ${url.pathname}`);
      return HttpResponse.json(apiError(failure.code, failure.message), {
        status: failure.status,
        headers: failure.status === 503 ? { 'Retry-After': '1' } : {},
      });
    }
    return null;
  };

  const newOrder = (customer: string, sku: string, price: string, seller: string | null): Order => {
    const order: Order = {
      order_id: ulid('01ORD'),
      customer_id: customer,
      status: 'PENDING',
      status_reason: null,
      total_amount: price,
      currency: 'ETH',
      items: [{ sku, quantity: 1, unit_price: price, seller }],
      created_at: NOW,
      updated_at: NOW,
    };
    market.orders.unshift(order);
    return order;
  };

  return [
    http.get('*/api/v1/categories', async ({ request }) => {
      return (
        (await record(request)) ??
        HttpResponse.json({
          items: [
            { slug: 'male', name: 'Male' },
            { slug: 'female', name: 'Female' },
            { slug: 'zombie', name: 'Zombie' },
            { slug: 'ape', name: 'Ape' },
            { slug: 'alien', name: 'Alien' },
          ],
        })
      );
    }),
    http.get('*/api/v1/products', async ({ request }) => {
      return (
        (await record(request)) ??
        HttpResponse.json(page(market.products, new URL(request.url).searchParams))
      );
    }),
    http.get('*/api/v1/products/:sku', async ({ request, params }) => {
      const failed = await record(request);
      if (failed) return failed;
      const product = market.products.find((p) => p.sku === params.sku);
      return product
        ? HttpResponse.json(product)
        : HttpResponse.json(apiError('PRODUCT_NOT_FOUND', 'no such product'), { status: 404 });
    }),
    http.post('*/api/v1/inventory/availability', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const { items } = (await request.json()) as { items: { sku: string; quantity: number }[] };
      const lines = items.map(({ sku, quantity }) => {
        const row = market.stock.get(sku);
        const available = row?.available ?? 0;
        return {
          sku,
          requested: quantity,
          available,
          sufficient: available >= quantity,
          reason: row ? (available >= quantity ? null : 'OUT_OF_STOCK') : 'UNKNOWN_SKU',
          owner: row?.owner ?? null,
        };
      });
      return HttpResponse.json({ available: lines.every((l) => l.sufficient), items: lines });
    }),
    http.get('*/api/v1/inventory/:sku', async ({ request, params }) => {
      const failed = await record(request);
      if (failed) return failed;
      const row = market.stock.get(String(params.sku));
      if (!row)
        return HttpResponse.json(apiError('INVENTORY_NOT_FOUND', 'no such item'), { status: 404 });
      return HttpResponse.json({
        sku: params.sku,
        available: row.available,
        reserved: 0,
        updated_at: NOW,
        owner: row.owner,
      });
    }),
    http.get('*/api/v1/listings', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const search = new URL(request.url).searchParams;
      const sku = search.get('sku');
      const status = search.get('status') ?? 'ACTIVE';
      const found = market.listings.filter(
        (l) =>
          (sku === null || l.sku === sku) &&
          (status === 'ALL' || (status === 'ACTIVE' ? active(l) : l.status === status)),
      );
      return HttpResponse.json(page(found, search));
    }),
    http.post('*/api/v1/listings', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const { customer_id, sku } = (await request.json()) as { customer_id: string; sku: string };
      if (market.stock.get(sku)?.owner !== customer_id) {
        return HttpResponse.json(apiError('NOT_OWNER', `${sku} is not yours to sell`), {
          status: 409,
        });
      }
      return HttpResponse.json(putUp(market, sku, customer_id), { status: 201 });
    }),
    http.delete('*/api/v1/listings/:sku', async ({ request, params }) => {
      const failed = await record(request);
      if (failed) return failed;
      const listing = market.listings.find((l) => l.sku === params.sku && active(l));
      if (!listing)
        return HttpResponse.json(apiError('NOT_LISTED', 'not up for bid'), { status: 409 });
      listing.status = 'CANCELLED';
      for (const b of market.bids)
        if (b.listing_id === listing.listing_id && b.status === 'OPEN') b.status = 'CLOSED';
      return HttpResponse.json(listing);
    }),
    http.get('*/api/v1/bids', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const search = new URL(request.url).searchParams;
      const sku = search.get('sku');
      const customer = search.get('customer_id');
      const found = market.bids.filter(
        (b) => (sku === null || b.sku === sku) && (customer === null || b.bidder === customer),
      );
      return HttpResponse.json(page(found, search));
    }),
    http.post('*/api/v1/bids', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const { customer_id, sku, amount } = (await request.json()) as {
        customer_id: string;
        sku: string;
        amount: string;
      };
      return HttpResponse.json(addBid(market, sku, customer_id, amount), { status: 201 });
    }),
    http.delete('*/api/v1/bids/:bidId', async ({ request, params }) => {
      const failed = await record(request);
      if (failed) return failed;
      const bid = market.bids.find((b) => b.bid_id === params.bidId);
      if (!bid) return HttpResponse.json(apiError('BID_NOT_FOUND', 'no such bid'), { status: 404 });
      bid.status = 'WITHDRAWN';
      return HttpResponse.json(bid);
    }),
    http.post('*/api/v1/bids/:bidId/accept', async ({ request, params }) => {
      const failed = await record(request);
      if (failed) return failed;
      const { customer_id } = (await request.json()) as { customer_id: string };
      const bid = market.bids.find((b) => b.bid_id === params.bidId);
      if (!bid) return HttpResponse.json(apiError('BID_NOT_FOUND', 'no such bid'), { status: 404 });
      const listing = market.listings.find((l) => l.listing_id === bid.listing_id);
      if (listing) listing.status = 'SALE_PENDING';
      bid.status = 'ACCEPTED';
      const order = newOrder(bid.bidder, bid.sku, bid.amount, customer_id);
      bid.order_id = order.order_id;
      return HttpResponse.json(order, { status: 202 });
    }),
    http.get('*/api/v1/activity', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const search = new URL(request.url).searchParams;
      const sku = search.get('sku');
      return HttpResponse.json(
        page(
          market.activity.filter((e) => sku === null || e.sku === sku),
          search,
        ),
      );
    }),
    http.post('*/api/v1/orders', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const { customer_id, items } = (await request.json()) as {
        customer_id: string;
        items: { sku: string }[];
      };
      const sku = items[0]?.sku ?? '';
      const product = market.products.find((p) => p.sku === sku);
      return HttpResponse.json(newOrder(customer_id, sku, product?.price ?? '0.00', null), {
        status: 202,
      });
    }),
    http.get('*/api/v1/orders/:id', async ({ request, params }) => {
      const failed = await record(request);
      if (failed) return failed;
      const order = market.orders.find((o) => o.order_id === params.id);
      return order
        ? HttpResponse.json(order)
        : HttpResponse.json(apiError('ORDER_NOT_FOUND', 'no such order'), { status: 404 });
    }),
    http.get('*/api/v1/orders', async ({ request }) => {
      const failed = await record(request);
      if (failed) return failed;
      const search = new URL(request.url).searchParams;
      return HttpResponse.json(
        page(
          market.orders.filter((o) => o.customer_id === search.get('customer_id')),
          search,
        ),
      );
    }),
    http.get('*/api/v1/notifications', async ({ request }) => {
      return (await record(request)) ?? HttpResponse.json({ items: [] });
    }),
  ];
}

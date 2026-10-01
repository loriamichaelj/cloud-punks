import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { BASKET_KEY } from '../lib/basket';
import { ATTEMPT_KEY } from '../lib/idempotency';
import { apiError, note, order, product } from '../test/fixtures';
import { renderApp } from '../test/render';
import { server } from '../test/server';

const categories = http.get('*/api/v1/categories', () =>
  HttpResponse.json({
    items: [
      { slug: 'apparel', name: 'Apparel' },
      { slug: 'footwear', name: 'Footwear' },
    ],
  }),
);

function availability(levels: Record<string, number>) {
  return http.post('*/api/v1/inventory/availability', async ({ request }) => {
    const body = (await request.json()) as { items: { sku: string; quantity: number }[] };
    return HttpResponse.json({
      available: body.items.every((i) => (levels[i.sku] ?? 0) >= i.quantity),
      items: body.items.map((i) => ({
        sku: i.sku,
        requested: i.quantity,
        available: levels[i.sku] ?? 0,
        sufficient: (levels[i.sku] ?? 0) >= i.quantity,
        reason: null,
      })),
    });
  });
}

function seedBasket(quantity = 2) {
  window.localStorage.setItem(
    BASKET_KEY,
    JSON.stringify([
      { sku: 'SKU-A', name: 'Product SKU-A', unitPrice: '19.99', currency: 'USD', quantity },
    ]),
  );
}

describe('catalog', () => {
  it('lists products with stock badges and disables add-to-basket when out of stock', async () => {
    server.use(
      categories,
      http.get('*/api/v1/products', () =>
        HttpResponse.json({
          items: [product('SKU-A'), product('SKU-B'), product('SKU-C')],
          page: 1,
          size: 20,
          total: 3,
        }),
      ),
      availability({ 'SKU-A': 50, 'SKU-B': 3, 'SKU-C': 0 }),
    );
    renderApp('/');

    const cards = await screen.findAllByRole('listitem');
    expect(await within(cards[0]!).findByText('In stock')).toBeInTheDocument();
    expect(await within(cards[1]!).findByText('Only 3 left')).toBeInTheDocument();
    expect(await within(cards[2]!).findByText('Out of stock')).toBeInTheDocument();
    expect(within(cards[2]!).getByRole('button', { name: /Add to basket/ })).toBeDisabled();
    expect(within(cards[0]!).getByText('$19.99')).toBeInTheDocument();
  });

  it('asks for the right category and page, and shows pagination', async () => {
    const seen: string[] = [];
    server.use(
      categories,
      http.get('*/api/v1/products', ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ items: [product('SKU-A')], page: 2, size: 20, total: 45 });
      }),
      availability({ 'SKU-A': 9 }),
    );
    const user = userEvent.setup();
    renderApp('/?category=footwear&page=2');

    expect(await screen.findByText('Page 2 of 3')).toBeInTheDocument();
    expect(seen[0]).toBe('?category=footwear&page=2&size=20');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => {
      expect(seen.some((s) => s.includes('page=3'))).toBe(true);
    });
  });

  it('shows a retryable error with the correlation id when the catalog fails', async () => {
    let fail = true;
    server.use(
      categories,
      http.get('*/api/v1/products', () =>
        fail
          ? HttpResponse.json(apiError('STORE_UNAVAILABLE', 'temporarily unavailable', 'corr-77'), {
              status: 503,
            })
          : HttpResponse.json({ items: [product('SKU-A')], page: 1, size: 20, total: 1 }),
      ),
      availability({ 'SKU-A': 9 }),
    );
    const user = userEvent.setup();
    renderApp('/');

    const panel = await screen.findByTestId('error-panel');
    expect(panel).toHaveTextContent('Could not load the catalog');
    expect(panel).toHaveTextContent('corr-77');
    fail = false;
    await user.click(within(panel).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Product SKU-A')).toBeInTheDocument();
  });

  it('never serves stock from cache: it is asked again when the page is shown again', async () => {
    let calls = 0;
    server.use(
      categories,
      http.get('*/api/v1/products', () =>
        HttpResponse.json({ items: [product('SKU-A')], page: 1, size: 20, total: 1 }),
      ),
      http.post('*/api/v1/inventory/availability', () => {
        calls += 1;
        const available = calls === 1 ? 9 : 0;
        return HttpResponse.json({
          available: available > 0,
          items: [
            { sku: 'SKU-A', requested: 1, available, sufficient: available > 0, reason: null },
          ],
        });
      }),
      http.get('*/api/v1/products/SKU-A', () => HttpResponse.json(product('SKU-A'))),
      http.get('*/api/v1/inventory/SKU-A', () =>
        HttpResponse.json({
          sku: 'SKU-A',
          available: 9,
          reserved: 0,
          updated_at: '2026-10-01T12:00:00Z',
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/');
    expect(await screen.findByText('In stock')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Product SKU-A' }));
    await screen.findByRole('heading', { name: 'Product SKU-A', level: 1 });
    await user.click(
      within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', {
        name: 'Catalog',
      }),
    );

    expect(await screen.findByText('Out of stock')).toBeInTheDocument();
    expect(calls).toBe(2);
  });
});

describe('basket', () => {
  it('shows an estimate, warns about short stock and lets the quantity change', async () => {
    seedBasket(5);
    server.use(availability({ 'SKU-A': 2 }));
    const user = userEvent.setup();
    renderApp('/basket');

    expect(await screen.findByText('Estimated total: $99.95')).toBeInTheDocument();
    expect(await screen.findByText('Only 2 available')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('may not be available');

    const qty = screen.getByLabelText('Quantity for Product SKU-A');
    await user.clear(qty);
    await user.type(qty, '2');
    expect(await screen.findByText('Estimated total: $39.98')).toBeInTheDocument();
    const stored = JSON.parse(window.localStorage.getItem(BASKET_KEY) ?? '[]') as {
      quantity: number;
    }[];
    expect(stored[0]?.quantity).toBe(2);
  });

  it('starts empty when the stored basket is corrupt', async () => {
    window.localStorage.setItem(BASKET_KEY, 'not json');
    renderApp('/basket');
    expect(await screen.findByText('Your basket is empty.')).toBeInTheDocument();
  });
});

describe('checkout', () => {
  const createdOrder = order({ order_id: '01J9Z6R0C4BBBBBBBBBBBBBBBB' });

  function orderRoutes() {
    return [
      http.get('*/api/v1/orders/01J9Z6R0C4BBBBBBBBBBBBBBBB', () => HttpResponse.json(createdOrder)),
      http.get('*/api/v1/notifications', () => HttpResponse.json({ items: [] })),
    ];
  }

  it('places the order with an idempotency key and a correlation id, then opens it', async () => {
    seedBasket(2);
    let headers: Headers | undefined;
    let body: unknown;
    server.use(
      ...orderRoutes(),
      http.post('*/api/v1/orders', async ({ request }) => {
        headers = request.headers;
        body = await request.json();
        return HttpResponse.json(createdOrder, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/checkout');

    expect(screen.getByRole('button', { name: 'Place order (demo, no payment)' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Place order (demo, no payment)' }));

    expect(
      await screen.findByRole('heading', { name: /Order 01J9Z6R0C4BBBBBBBBBBBBBBBB/ }),
    ).toBeInTheDocument();
    expect(headers?.get('idempotency-key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(headers?.get('x-correlation-id')).toBeTruthy();
    expect(body).toMatchObject({ items: [{ sku: 'SKU-A', quantity: 2 }] });
    expect(window.localStorage.getItem(BASKET_KEY)).toBe('[]'); // the basket is spent
    expect(window.localStorage.getItem(ATTEMPT_KEY)).toBeNull(); // so is the attempt
  });

  it('reuses the same key when the user retries after a failure', async () => {
    seedBasket(1);
    const keys: string[] = [];
    let fail = true;
    server.use(
      ...orderRoutes(),
      http.post('*/api/v1/orders', ({ request }) => {
        keys.push(request.headers.get('idempotency-key') ?? '');
        return fail ? HttpResponse.error() : HttpResponse.json(createdOrder, { status: 200 }); // a replay is success too
      }),
    );
    const user = userEvent.setup();
    renderApp('/checkout');
    await user.click(screen.getByRole('button', { name: 'Place order (demo, no payment)' }));

    const panel = await screen.findByTestId('error-panel');
    expect(panel).toHaveTextContent('could not be reached');
    expect(panel).toHaveTextContent('connection problem, not a server error');
    fail = false;
    await user.click(within(panel).getByRole('button', { name: 'Try again' }));

    expect(await screen.findByRole('heading', { name: /Order 01J9/ })).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });

  it('shows the server message for an out-of-stock order and links back to the basket', async () => {
    seedBasket(5);
    server.use(
      http.post('*/api/v1/orders', () =>
        HttpResponse.json(apiError('OUT_OF_STOCK', 'SKU-A: requested 5, available 1', 'corr-409'), {
          status: 409,
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/checkout');
    await user.click(screen.getByRole('button', { name: 'Place order (demo, no payment)' }));

    const panel = await screen.findByTestId('error-panel');
    expect(panel).toHaveTextContent('SKU-A: requested 5, available 1');
    expect(panel).toHaveTextContent('corr-409');
    expect(within(panel).getByRole('link', { name: 'Back to the basket' })).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('marks the lines the server says are unknown', async () => {
    seedBasket(1);
    server.use(
      http.post('*/api/v1/orders', () =>
        HttpResponse.json(apiError('UNKNOWN_PRODUCT', 'unknown product(s): SKU-A'), {
          status: 422,
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/checkout');
    await user.click(screen.getByRole('button', { name: 'Place order (demo, no payment)' }));

    expect(await screen.findByText(/no longer available/)).toBeInTheDocument();
  });

  it('keeps retrying a 503 with the same key, then offers a button', async () => {
    seedBasket(1);
    const keys: string[] = [];
    server.use(
      http.post('*/api/v1/orders', ({ request }) => {
        keys.push(request.headers.get('idempotency-key') ?? '');
        return HttpResponse.json(apiError('STORE_UNAVAILABLE', 'later'), {
          status: 503,
          headers: { 'Retry-After': '0' }, // no wait in the test
        });
      }),
    );
    const user = userEvent.setup();
    renderApp('/checkout');
    await user.click(screen.getByRole('button', { name: 'Place order (demo, no payment)' }));

    await screen.findByTestId('error-panel', undefined, { timeout: 15_000 });
    expect(keys).toHaveLength(4); // the first try and 3 automatic retries
    expect(new Set(keys).size).toBe(1);
  }, 20_000);

  it('rejects an invalid customer id before calling the API', async () => {
    seedBasket(1);
    const user = userEvent.setup();
    renderApp('/checkout');
    const input = screen.getByLabelText(/Customer id/);
    await user.clear(input);
    await user.type(input, 'has space');
    expect(screen.getByRole('button', { name: 'Place order (demo, no payment)' })).toBeDisabled();
  });
});

describe('order tracking', () => {
  const id = '01J9Z6R0C4AAAAAAAAAAAAAAAA';

  it('shows a rejected order with its reason, snapshotted prices, the authoritative total and notifications', async () => {
    server.use(
      http.get(`*/api/v1/orders/${id}`, () =>
        HttpResponse.json(order({ status: 'REJECTED', status_reason: 'OUT_OF_STOCK' })),
      ),
      http.get('*/api/v1/notifications', () =>
        HttpResponse.json({
          items: [
            note(
              'InventoryFailed',
              'We could not reserve stock for order X: some items are out of stock.',
              'N1',
            ),
            note('OrderStatusUpdated', 'Your order X was rejected (OUT_OF_STOCK).', 'N2'),
          ],
        }),
      ),
    );
    renderApp(`/orders/${id}`);

    const status = await screen.findByTestId('order-status');
    expect(status).toHaveAttribute('data-status', 'REJECTED');
    expect(screen.getByText('OUT_OF_STOCK', { selector: 'code' })).toBeInTheDocument();
    expect(
      screen.getByText((_, el) => el?.tagName === 'STRONG' && el.textContent === 'Total: $39.98'),
    ).toBeInTheDocument();
    expect(screen.getByText('$19.99')).toBeInTheDocument();
    expect(await screen.findByText(/could not reserve stock/)).toBeInTheDocument();
    expect(screen.getByText(/was rejected \(OUT_OF_STOCK\)/)).toBeInTheDocument();
  });

  it('polls a PENDING order until it is CONFIRMED', async () => {
    let calls = 0;
    server.use(
      http.get(`*/api/v1/orders/${id}`, () => {
        calls += 1;
        return HttpResponse.json(order({ status: calls < 3 ? 'PENDING' : 'CONFIRMED' }));
      }),
      http.get('*/api/v1/notifications', () => HttpResponse.json({ items: [] })),
    );
    renderApp(`/orders/${id}`);

    expect(await screen.findByTestId('order-status')).toHaveAttribute('data-status', 'PENDING');
    await waitFor(
      () => {
        expect(screen.getByTestId('order-status')).toHaveAttribute('data-status', 'CONFIRMED');
      },
      { timeout: 8000 },
    );
    const settled = calls;
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(calls).toBe(settled); // polling stopped at the terminal status
  }, 15_000);

  it('shows an error panel for an order that does not exist', async () => {
    server.use(
      http.get(`*/api/v1/orders/${id}`, () =>
        HttpResponse.json(apiError('ORDER_NOT_FOUND', "order 'x' not found"), { status: 404 }),
      ),
      http.get('*/api/v1/notifications', () => HttpResponse.json({ items: [] })),
    );
    renderApp(`/orders/${id}`);
    expect(await screen.findByTestId('error-panel')).toHaveTextContent('not found');
  });
});

describe('my orders', () => {
  it('lists the customer’s orders, newest first, from the API', async () => {
    let queried = '';
    server.use(
      http.get('*/api/v1/orders', ({ request }) => {
        queried = new URL(request.url).search;
        return HttpResponse.json({
          items: [order({ order_id: '01J9Z6R0C4CCCCCCCCCCCCCCCC', status: 'CONFIRMED' })],
          page: 1,
          size: 20,
          total: 1,
        });
      }),
    );
    window.localStorage.setItem('retail.customer.v1', 'cust-test');
    renderApp('/orders');

    expect(
      await screen.findByRole('link', { name: '01J9Z6R0C4CCCCCCCCCCCCCCCC' }),
    ).toBeInTheDocument();
    expect(queried).toBe('?customer_id=cust-test&page=1&size=20');
    expect(screen.getByText('CONFIRMED')).toBeInTheDocument();
  });
});

describe('unknown routes and demo tools', () => {
  it('shows a not-found page', async () => {
    renderApp('/nope');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('has no demo tools route unless the build enables them', async () => {
    renderApp('/demo');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

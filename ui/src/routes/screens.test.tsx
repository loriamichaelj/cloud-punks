// Every screen against an in-memory market (src/test/market.ts) at the network boundary, as the
// customer ME. What is checked is what a person sees and what the screens send.

import { screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { CUSTOMER_KEY } from '../lib/customer';
import { CORRELATION_HEADER } from '../lib/correlation';
import { ME, addBid, marketHandlers, newMarket, putUp, type Market } from '../test/market';
import { renderApp } from '../test/render';
import { server } from '../test/server';

let market: Market;

beforeEach(() => {
  market = newMarket();
  server.use(...marketHandlers(market));
  window.localStorage.setItem(CUSTOMER_KEY, ME);
});

const card = (sku: string) =>
  screen.getAllByTestId('punk-card').find((c) => c.dataset.sku === sku)!;
const sent = (method: string, path: string) =>
  market.requests.filter((r) => r.method === method && r.path === `/api/v1${path}`);

// -- the collection -------------------------------------------------------------------------

describe('the collection', () => {
  it('shows every CloudPunk on the colour of its market state, with the header figures', async () => {
    renderApp('/');

    await screen.findAllByTestId('punk-card');
    expect(card('CP-0001').dataset.state).toBe('unsold');
    expect(card('CP-0002').dataset.state).toBe('owned');
    expect(card('CP-0003').dataset.state).toBe('bid');
    expect(within(card('CP-0001')).getByText('31.43 ETH')).toBeInTheDocument();
    expect(within(card('CP-0003')).getByText('Up for bid')).toBeInTheDocument();
    expect(within(card('CP-0002')).getByText('Last sale 9.50 ETH')).toBeInTheDocument();
    expect(within(card('CP-0002')).getByRole('link', { name: 'you' })).toBeInTheDocument();

    const stats = screen.getByTestId('collection-stats');
    expect(within(stats).getByText('31.43 ETH')).toBeInTheDocument(); // the floor: the cheapest unsold
    expect(within(stats).getByText('Owners').closest('div')).toHaveTextContent('2'); // me and Bob
  });

  it('filters by status, type and trait, and the URL keeps the filter', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findAllByTestId('punk-card');

    await user.click(screen.getByRole('checkbox', { name: /Buy now/ }));
    expect(screen.getByTestId('result-count')).toHaveTextContent('2 items');
    await user.click(screen.getByRole('checkbox', { name: /Zombie/ }));
    expect(screen.getAllByTestId('punk-card').map((c) => c.dataset.sku)).toEqual(['CP-0004']);

    await user.click(screen.getByRole('button', { name: /Clear all filters/ }));
    expect(screen.getByTestId('result-count')).toHaveTextContent('4 items');
  });

  it('keeps the item count still while the market refreshes in the background', async () => {
    const { client } = renderApp('/');
    await screen.findAllByTestId('punk-card');
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    // hold the refresh open, then let the market's own handler answer
    server.use(http.get('*/api/v1/listings', () => gate.then(() => undefined)));

    const refresh = client.refetchQueries({ queryKey: ['market'] });
    await waitFor(() => {
      expect(client.isFetching({ queryKey: ['market'] })).toBe(1);
    });
    expect(screen.getByTestId('result-count').textContent).toBe('4 items');
    release();
    await refresh;
    expect(screen.getByTestId('result-count').textContent).toBe('4 items');
  });

  it('starts from the filters in the URL, sorts, and searches by number or trait', async () => {
    const user = userEvent.setup();
    renderApp('/?trait=Earring&sort=price-desc');
    await screen.findAllByTestId('punk-card');

    expect(screen.getAllByTestId('punk-card').map((c) => c.dataset.sku)).toEqual([
      'CP-0004',
      'CP-0001',
      'CP-0003',
    ]);
    await user.selectOptions(screen.getByLabelText('Sort by'), 'number');
    expect(screen.getAllByTestId('punk-card').map((c) => c.dataset.sku)).toEqual([
      'CP-0001',
      'CP-0003',
      'CP-0004',
    ]);

    await user.type(screen.getByLabelText('Search the collection'), 'pipe{Enter}');
    expect(screen.getAllByTestId('punk-card').map((c) => c.dataset.sku)).toEqual(['CP-0004']);
  });

  it('re-reads stock and listings on every visit, never serving them from a cache', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findAllByTestId('punk-card');
    const reads = () => sent('POST', '/inventory/availability').length;
    const before = reads();

    market.stock.set('CP-0001', { available: 0, owner: 'cust-zed' }); // sold elsewhere
    await user.click(within(card('CP-0004')).getAllByRole('link')[0]!); // to its page...
    await screen.findByTestId('price-panel');
    await user.click(screen.getAllByRole('link', { name: 'CloudPunks' })[0]!); // ...and back

    await waitFor(() => {
      expect(card('CP-0001').dataset.state).toBe('owned');
    });
    expect(reads()).toBeGreaterThan(before);
  });

  it('shows a failure with the server reference, and recovers on retry', async () => {
    const user = userEvent.setup();
    market.failNext.set('POST /api/v1/inventory/availability', {
      status: 500,
      code: 'BOOM',
      message: 'inventory fell over',
    });
    renderApp('/');

    const panel = await screen.findByTestId('error-panel');
    expect(panel).toHaveTextContent('inventory fell over');
    expect(panel).toHaveTextContent('corr-from-server');
    await user.click(within(panel).getByRole('button', { name: 'Try again' }));
    expect(await screen.findAllByTestId('punk-card')).toHaveLength(4);
  });

  it('sends a correlation id with every request', async () => {
    renderApp('/');
    await screen.findAllByTestId('punk-card');
    expect(market.requests.length).toBeGreaterThan(3);
    expect(market.requests.every((r) => (r.headers.get(CORRELATION_HEADER) ?? '').length > 0)).toBe(
      true,
    );
  });

  it('lists the activity with who it came from and went to', async () => {
    renderApp('/activity');
    const table = await screen.findByTestId('activity-table');
    const row = within(table).getByText('Sale').closest('tr')!;
    expect(row).toHaveTextContent('CloudPunk #0002');
    expect(row).toHaveTextContent('9.50 ETH');
    expect(row).toHaveTextContent('CloudPunks'); // from the platform
  });
});

// -- a CloudPunk ----------------------------------------------------------------------------

describe('a CloudPunk', () => {
  it('unsold: shows the price and buys it after a confirm step, then follows the order', async () => {
    const user = userEvent.setup();
    renderApp('/cloudpunks/0001');

    expect(await screen.findByTestId('current-price')).toHaveTextContent('31.43 ETH');
    expect(screen.getByText('Mohawk Thin')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Buy now' }));
    await user.click(screen.getByRole('button', { name: 'Confirm purchase' }));

    expect(await screen.findByTestId('order-status')).toHaveAttribute('data-status', 'PENDING');
    const [post] = sent('POST', '/orders');
    expect(post?.body).toEqual({ customer_id: ME, items: [{ sku: 'CP-0001', quantity: 1 }] });
    expect(post?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('unsold: a failed purchase keeps its Idempotency-Key, so retrying cannot buy twice', async () => {
    const user = userEvent.setup();
    market.failNext.set('POST /api/v1/orders', {
      status: 409,
      code: 'OUT_OF_STOCK',
      message: 'CP-0001: requested 1, available 0',
    });
    renderApp('/cloudpunks/0001?buy=1');

    await user.click(await screen.findByRole('button', { name: 'Confirm purchase' }));
    expect(await screen.findByTestId('error-panel')).toHaveTextContent('requested 1, available 0');
    await user.click(screen.getByRole('button', { name: 'Confirm purchase' }));

    await screen.findByTestId('order-status');
    const keys = sent('POST', '/orders').map((r) => r.headers.get('Idempotency-Key'));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('owned by me: puts it up for bid', async () => {
    const user = userEvent.setup();
    renderApp('/cloudpunks/0002');

    await user.click(await screen.findByRole('button', { name: 'Put up for bid' }));

    await waitFor(() => {
      expect(sent('POST', '/listings')[0]?.body).toEqual({ customer_id: ME, sku: 'CP-0002' });
    });
    expect(await screen.findByRole('button', { name: 'Take off the market' })).toBeInTheDocument();
  });

  it('owned by someone else and not listed: nothing to do', async () => {
    market.stock.set('CP-0004', { available: 0, owner: 'cust-zed' });
    renderApp('/cloudpunks/0004');
    expect(await screen.findByText('Only its owner can put it up for bid.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Buy now|Make offer|Put up/ })).toBeNull();
  });

  it('up for bid by someone else: refuses a bad amount and places a good one as a string', async () => {
    const user = userEvent.setup();
    addBid(market, 'CP-0003', 'cust-carol', '18.00');
    renderApp('/cloudpunks/0003');

    expect(await screen.findByText('Top bid, by cust-carol')).toBeInTheDocument();
    const input = screen.getByLabelText('Your offer (ETH)');
    await user.type(input, '12.345');
    await user.click(screen.getByRole('button', { name: 'Make offer' }));
    expect(screen.getByText(/at most two decimals/)).toBeInTheDocument();
    expect(sent('POST', '/bids')).toHaveLength(0);

    await user.clear(input);
    await user.type(input, '25.5');
    await user.click(screen.getByRole('button', { name: 'Make offer' }));

    expect(await screen.findByText(/Offer placed/)).toBeInTheDocument();
    const [post] = sent('POST', '/bids');
    expect(post?.body).toEqual({ customer_id: ME, sku: 'CP-0003', amount: '25.5' });
    expect(post?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('up for bid by me: accepts a bid and can take it off the market', async () => {
    const user = userEvent.setup();
    putUp(market, 'CP-0002', ME);
    addBid(market, 'CP-0002', 'cust-carol', '14.00');
    renderApp('/cloudpunks/0002');

    const offers = await screen.findByTestId('offers-table');
    expect(screen.getByRole('button', { name: 'Take off the market' })).toBeInTheDocument();
    await user.click(within(offers).getByRole('button', { name: 'Accept 14.00 ETH' }));

    expect(await screen.findByText(/Bid accepted/)).toBeInTheDocument();
    expect(sent('POST', `/bids/${market.bids[0]!.bid_id}/accept`)[0]?.body).toEqual({
      customer_id: ME,
    });
    expect(await screen.findByText('Sale being confirmed')).toBeInTheDocument();
  });

  it('up for bid by me: taking it off sends the owner and turns it blue', async () => {
    const user = userEvent.setup();
    putUp(market, 'CP-0002', ME);
    renderApp('/cloudpunks/0002');

    await user.click(await screen.findByRole('button', { name: 'Take off the market' }));

    await waitFor(() => {
      expect(sent('DELETE', '/listings/CP-0002')[0]?.search.get('customer_id')).toBe(ME);
    });
    expect(await screen.findByRole('button', { name: 'Put up for bid' })).toBeInTheDocument();
  });

  it('withdraws my own open bid', async () => {
    const user = userEvent.setup();
    const bid = addBid(market, 'CP-0003', ME, '21.00');
    renderApp('/cloudpunks/0003');

    await user.click(await screen.findByRole('button', { name: 'Withdraw 21.00 ETH' }));

    await waitFor(() => {
      expect(sent('DELETE', `/bids/${bid.bid_id}`)).toHaveLength(1);
    });
    expect(await screen.findByText('withdrawn')).toBeInTheDocument();
  });

  it('is not found for a number outside the collection', async () => {
    renderApp('/cloudpunks/0101');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

// -- my CloudPunks and orders ---------------------------------------------------------------

describe('my CloudPunks', () => {
  it('lists what I own, my bids and my orders', async () => {
    const user = userEvent.setup();
    addBid(market, 'CP-0003', ME, '21.00');
    renderApp('/account');

    expect(await screen.findByText('CloudPunk #0002')).toBeInTheDocument();
    expect(screen.queryByText('CloudPunk #0001')).toBeNull();
    await user.click(screen.getByRole('link', { name: 'Bids' }));
    expect(await screen.findByText('21.00 ETH')).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Orders' }));
    expect(await screen.findByText('No orders yet.')).toBeInTheDocument();
  });

  it('says what a confirmed order means', async () => {
    renderApp('/cloudpunks/0001?buy=1');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Confirm purchase' }));
    await screen.findByTestId('order-status');
    market.orders[0]!.status = 'CONFIRMED';

    await waitFor(
      () => {
        expect(screen.getByTestId('order-status')).toHaveTextContent(
          'You now own CloudPunk #0001.',
        );
      },
      { timeout: 3000 },
    );
  });
});

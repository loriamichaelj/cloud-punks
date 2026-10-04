// The header's customer menu: switch between the customers this browser has acted as, or create
// one, so one person can play buyer, seller and bidder. Against the in-memory market.

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { CUSTOMER_KEY, KNOWN_CUSTOMERS_KEY } from '../lib/customer';
import { ME, marketHandlers, newMarket, type Market } from '../test/market';
import { renderApp } from '../test/render';
import { server } from '../test/server';

let market: Market;

beforeEach(() => {
  market = newMarket();
  server.use(...marketHandlers(market));
  window.localStorage.setItem(CUSTOMER_KEY, ME);
});

const pill = () => screen.getByTestId('customer-menu');
const panel = () => pill().parentElement!;
const known = () => JSON.parse(window.localStorage.getItem(KNOWN_CUSTOMERS_KEY) ?? '[]') as unknown;

async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(pill());
  expect(panel()).toHaveAttribute('open');
}

async function create(user: ReturnType<typeof userEvent.setup>, name: string) {
  if (!panel().hasAttribute('open')) await open(user); // an invalid name leaves it open
  const input = within(panel()).getByLabelText('New customer');
  await user.clear(input);
  if (name) await user.type(input, name);
  await user.click(within(panel()).getByRole('button', { name: 'Create' }));
}

describe('the customer menu', () => {
  it('creates a named customer, acts as them, and switches back', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findAllByTestId('punk-card');

    await create(user, 'alice');
    expect(pill()).toHaveTextContent('alice');
    expect(panel()).not.toHaveAttribute('open');
    expect(screen.getByText('You are now alice.')).toBeInTheDocument();
    expect(window.localStorage.getItem(CUSTOMER_KEY)).toBe('alice');
    expect(known()).toEqual([ME, 'alice']);

    await open(user);
    expect(within(panel()).getByRole('button', { name: /alice/ })).toHaveAttribute(
      'aria-current',
      'true',
    );
    await user.click(within(panel()).getByRole('button', { name: ME }));
    expect(pill()).toHaveTextContent(ME);
    expect(window.localStorage.getItem(CUSTOMER_KEY)).toBe(ME);
    expect(known()).toEqual([ME, 'alice']); // switching never adds a duplicate
  });

  it('generates an id when no name is given, and refuses one the API would refuse', async () => {
    const user = userEvent.setup();
    renderApp('/');

    await create(user, 'not valid!');
    expect(within(panel()).getByText(/Use letters, digits/)).toBeInTheDocument();
    expect(pill()).toHaveTextContent(ME);

    await create(user, '');
    expect(pill().textContent).toMatch(/cust-[0-9a-f]{8}/);
    expect(known()).toHaveLength(2);
  });

  it('forgets a customer, but never the one you are', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(KNOWN_CUSTOMERS_KEY, JSON.stringify([ME, 'cust-bob']));
    renderApp('/');

    await open(user);
    expect(within(panel()).queryByRole('button', { name: `Forget ${ME}` })).toBeNull();
    await user.click(within(panel()).getByRole('button', { name: 'Forget cust-bob' }));
    expect(within(panel()).queryByRole('button', { name: 'cust-bob' })).toBeNull();
    expect(known()).toEqual([ME]);
  });

  it('closes on Escape and gives focus back to the pill', async () => {
    const user = userEvent.setup();
    renderApp('/');

    await open(user);
    await user.keyboard('{Escape}');
    expect(panel()).not.toHaveAttribute('open');
    expect(pill()).toHaveFocus();
  });

  it("a CloudPunk's page follows the switch: the owner's actions only for its owner", async () => {
    const user = userEvent.setup();
    renderApp('/cloudpunks/0002'); // owned by ME

    expect(await screen.findByRole('button', { name: 'Put up for bid' })).toBeInTheDocument();
    await create(user, 'carol');
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Put up for bid' })).toBeNull();
    });

    await open(user);
    await user.click(within(panel()).getByRole('button', { name: ME }));
    expect(await screen.findByRole('button', { name: 'Put up for bid' })).toBeInTheDocument();
  });
});

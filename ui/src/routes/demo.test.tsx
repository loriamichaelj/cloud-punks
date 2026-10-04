// The demo page exists only in builds with VITE_DEMO_TOOLS; here the flag is forced on.

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CUSTOMER_KEY, KNOWN_CUSTOMERS_KEY } from '../lib/customer';
import { ME, marketHandlers, newMarket } from '../test/market';
import { renderApp } from '../test/render';
import { server } from '../test/server';

vi.mock('../config', () => ({ DEMO_TOOLS: true }));

beforeEach(() => {
  server.use(...marketHandlers(newMarket()));
  window.localStorage.setItem(CUSTOMER_KEY, ME);
});

describe('demo tools', () => {
  it('switches the customer, which the header and storage follow', async () => {
    const user = userEvent.setup();
    renderApp('/demo');

    await user.click(await screen.findByRole('button', { name: 'Be cust-bob' }));

    expect(screen.getByText(/You are now cust-bob\./)).toBeInTheDocument();
    expect(screen.getByTestId('customer-menu')).toHaveTextContent('cust-bob');
    expect(window.localStorage.getItem(CUSTOMER_KEY)).toBe('cust-bob');
    // the header menu remembers both, to switch back
    expect(JSON.parse(window.localStorage.getItem(KNOWN_CUSTOMERS_KEY)!)).toEqual([ME, 'cust-bob']);
  });

  it('refuses an id the API would refuse', async () => {
    const user = userEvent.setup();
    renderApp('/demo');
    const input = await screen.findByLabelText('Customer id');

    await user.clear(input);
    await user.type(input, 'not valid!');
    await user.click(screen.getByRole('button', { name: 'Switch customer' }));

    expect(screen.getByText(/Use letters, digits/)).toBeInTheDocument();
    expect(window.localStorage.getItem(CUSTOMER_KEY)).toBe(ME);
  });
});

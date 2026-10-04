// Browser journeys against the Compose stack through the gateway (`make up seed`, then
// `make ui-e2e`). Each journey owns a few CloudPunks (#0091 to #0096) and hands them back to the
// platform afterwards, so the collection is all red again when the suite ends.

import { expect, test } from '@playwright/test';
import {
  actAs,
  buyAs,
  cardFor,
  compose,
  expectNoSeriousViolations,
  ownerOf,
  resetPunk,
  uniqueCustomer,
} from './helpers';

const OWNED = ['CP-0091', 'CP-0092', 'CP-0093', 'CP-0094', 'CP-0095', 'CP-0096'];

test.beforeAll(async ({ request }) => {
  for (const sku of OWNED) await resetPunk(request, sku);
});

test.afterAll(async ({ request }) => {
  for (const sku of OWNED) await resetPunk(request, sku);
});

test('browse the collection: 100 tiles by colour, filter and clear', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'CloudPunks', level: 1 })).toBeVisible();
  const cards = page.getByTestId('punk-card');
  await expect(cards).toHaveCount(100);
  await expect(cardFor(page, 'CP-0091')).toHaveAttribute('data-state', 'unsold');

  const zombie = page.getByRole('checkbox', { name: /Zombie/ });
  await zombie.click(); // the state comes from the URL, a moment after the click
  await expect(zombie).toBeChecked();
  await expect(page).toHaveURL(/type=zombie/);
  await expect(cards).toHaveCount(6);
  await page.getByRole('button', { name: /Clear all filters/ }).click();
  await expect(cards).toHaveCount(100);
  await expectNoSeriousViolations(page);
});

test('the header search jumps straight to a CloudPunk', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Search CloudPunks by number or trait').fill('#42');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/cloudpunks\/0042$/);
  await expect(page.getByRole('heading', { name: 'CloudPunk #0042', level: 1 })).toBeVisible();
  await expect(page.getByTestId('current-price')).toContainText('ETH');
  await expectNoSeriousViolations(page);
});

test('buy an unsold CloudPunk: the order confirms and its tile turns blue', async ({
  page,
  request,
}) => {
  const me = uniqueCustomer('pw-buyer');
  await actAs(page, me);
  await page.goto('/');
  await cardFor(page, 'CP-0091').hover();
  await cardFor(page, 'CP-0091').getByRole('link', { name: 'Buy now CloudPunk #0091' }).click();

  await page.getByRole('button', { name: 'Confirm purchase' }).click();
  const status = page.getByTestId('order-status');
  await expect(status).toHaveAttribute('data-status', 'CONFIRMED');
  await expect(status).toContainText('You now own CloudPunk #0091.');
  await expectNoSeriousViolations(page);
  expect(await ownerOf(request, 'CP-0091')).toBe(me);

  await page.goto('/');
  await expect(cardFor(page, 'CP-0091')).toHaveAttribute('data-state', 'owned');
  await expect(cardFor(page, 'CP-0091')).toContainText('Owned by you');
});

test('a resale end to end: put up for bid (purple), bid as someone else, accept', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const alice = uniqueCustomer('pw-alice');
  const bob = uniqueCustomer('pw-bob');
  await buyAs(request, alice, 'CP-0092');

  await actAs(page, alice);
  await page.goto('/cloudpunks/0092');
  await page.getByRole('button', { name: 'Put up for bid' }).click();
  await expect(page.getByRole('button', { name: 'Take off the market' })).toBeVisible();
  await page.goto('/');
  await expect(cardFor(page, 'CP-0092')).toHaveAttribute('data-state', 'bid');

  // the demo page switches the customer, as a second person would
  await page.goto('/demo');
  await page.getByLabel('Customer id').fill(bob);
  await page.getByRole('button', { name: 'Switch customer' }).click();
  await expect(page.getByRole('status')).toContainText(`You are now ${bob}.`);
  await expectNoSeriousViolations(page);
  await page.goto('/cloudpunks/0092');
  await page.getByLabel('Your offer (ETH)').fill('15.00');
  await page.getByRole('button', { name: 'Make offer' }).click();
  await expect(page.getByText('Offer placed.')).toBeVisible();
  await expectNoSeriousViolations(page);

  await page.goto('/demo');
  await page.getByLabel('Customer id').fill(alice);
  await page.getByRole('button', { name: 'Switch customer' }).click();
  await page.goto('/cloudpunks/0092');
  await page.getByRole('button', { name: 'Accept 15.00 ETH' }).click();
  await expect(page.getByText(/Bid accepted/)).toBeVisible();

  await expect.poll(async () => ownerOf(request, 'CP-0092'), { timeout: 30_000 }).toBe(bob);
  await page.goto('/cloudpunks/0092');
  await expect(page.getByText(`Owned by ${bob}`)).toBeVisible();
  const activity = page.getByTestId('activity-table');
  await expect(activity.getByRole('row').filter({ hasText: 'Sale' }).first()).toContainText(
    '15.00 ETH',
  );
});

test('double-clicking Confirm purchase creates one order', async ({ page, request }) => {
  const me = uniqueCustomer('pw-double');
  await actAs(page, me);
  await page.goto('/cloudpunks/0093?buy=1');
  await page.getByRole('button', { name: 'Confirm purchase' }).dblclick();
  await expect(page.getByTestId('order-status')).toHaveAttribute('data-status', 'CONFIRMED');

  const orders = (await (await request.get(`/api/v1/orders?customer_id=${me}`)).json()) as {
    total: number;
  };
  expect(orders.total).toBe(1);
});

test('someone else buys it first: the error says so and carries a reference', async ({
  page,
  request,
}) => {
  await actAs(page, uniqueCustomer('pw-late'));
  await page.goto('/cloudpunks/0094?buy=1');
  await expect(page.getByTestId('current-price')).toBeVisible();
  await buyAs(request, uniqueCustomer('pw-early'), 'CP-0094');

  await page.getByRole('button', { name: 'Confirm purchase' }).click();
  const panel = page.getByTestId('error-panel');
  await expect(panel).toContainText('requested 1, available 0');
  await expect(panel).toContainText(/Reference\s+\S+/);
  await expectNoSeriousViolations(page);
});

test('my CloudPunks lists what I own, my bids and my orders', async ({ page, request }) => {
  const me = uniqueCustomer('pw-profile');
  await buyAs(request, me, 'CP-0095');
  await actAs(page, me);
  await page.goto('/account');
  await expect(page.getByRole('heading', { name: 'My CloudPunks' })).toBeVisible();
  await expect(cardFor(page, 'CP-0095')).toBeVisible();
  await expectNoSeriousViolations(page);
  await page.getByRole('link', { name: 'Orders' }).click();
  await expect(page.getByTestId('orders-table')).toContainText('CloudPunk #0095');
});

test('stopping product-service shows a retryable error and recovers', async ({ page, request }) => {
  test.setTimeout(150_000);
  compose('stop', 'product-service');
  try {
    await page.goto('/');
    const panel = page.getByTestId('error-panel');
    await expect(panel).toContainText('Could not load the collection');
    await expect(panel).toContainText(/Reference\s+\S+/);
    await expectNoSeriousViolations(page);
  } finally {
    compose('start', 'product-service');
  }
  await expect
    .poll(async () => (await request.get('/api/v1/categories')).status(), { timeout: 60_000 })
    .toBe(200);
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByTestId('punk-card')).toHaveCount(100);
});

test('an unreachable gateway is reported as a network error, not an API error', async ({
  page,
}) => {
  await page.route('**/api/v1/**', (route) => route.abort('connectionrefused'));
  await page.goto('/');
  const panel = page.getByTestId('error-panel');
  await expect(panel).toContainText('could not be reached');
  await expect(panel).toContainText('connection problem, not a server error');
});

test('a page at phone width has no horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  for (const path of ['/', '/cloudpunks/0096', '/activity', '/account']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

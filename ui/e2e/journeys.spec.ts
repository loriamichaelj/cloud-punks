import { expect, test } from '@playwright/test';
import {
  addFromProductPage,
  checkout,
  compose,
  expectNoSeriousViolations,
  setStock,
  stockOf,
  uniqueCustomer,
} from './helpers';

const CONFIRM_SKU = 'SKU-MUG-WHT';
const SYNC_SKU = 'SKU-VASE-GLS';
const ASYNC_SKU = 'SKU-CANDLE-VAN';
const DOUBLE_SKU = 'SKU-THROW-GRY';
const PAGER_SKU = 'SKU-CAP-NAVY';

test('browse the catalog and filter by category', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Catalog' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Products' }).getByRole('listitem')).toHaveCount(20);

  await page.getByRole('button', { name: 'Footwear' }).click();
  const cards = page.getByRole('list', { name: 'Products' }).getByRole('listitem');
  await expect(cards).toHaveCount(4);
  await expect(page).toHaveURL(/category=footwear/);

  await page.getByRole('button', { name: 'All', exact: true }).click();
  await expect(cards).toHaveCount(20);
  await expectNoSeriousViolations(page);
});

test('stock badges show In stock, Only N left and Out of stock', async ({ page, request }) => {
  await setStock(request, 'SKU-SCARF-RED', 3);
  await setStock(request, 'SKU-WALLET-BRN', 0);
  await page.goto('/');
  const scarf = page.getByRole('listitem').filter({ hasText: 'Red Scarf' });
  const wallet = page.getByRole('listitem').filter({ hasText: 'Brown Wallet' });
  await expect(scarf.getByText('Only 3 left')).toBeVisible();
  await expect(wallet.getByText('Out of stock')).toBeVisible();
  await expect(wallet.getByRole('button', { name: /Add to basket/ })).toBeDisabled();
  await setStock(request, 'SKU-SCARF-RED', 25);
  await setStock(request, 'SKU-WALLET-BRN', 25);
});

test('the basket survives a reload', async ({ page, request }) => {
  await setStock(request, CONFIRM_SKU, 50);
  await addFromProductPage(page, CONFIRM_SKU, 3);
  await page.goto('/basket');
  await expect(page.getByRole('link', { name: 'Basket (3)' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('link', { name: 'Basket (3)' })).toBeVisible();
  await expect(page.getByLabel('Quantity for White Mug')).toHaveValue('3');
  await expect(page.getByText(/Estimated total/).first()).toBeVisible();
  await expectNoSeriousViolations(page);
});

test('checkout shows PENDING then CONFIRMED and stock drops by exactly the quantity', async ({
  page,
  request,
}) => {
  await setStock(request, CONFIRM_SKU, 20);
  const customer = uniqueCustomer();
  await addFromProductPage(page, CONFIRM_SKU, 2);
  await page.goto('/checkout');
  await expectNoSeriousViolations(page);

  await checkout(page, customer);
  await expect(page).toHaveURL(/\/orders\/[0-9A-Z]{26}$/);
  const status = page.getByTestId('order-status');
  await expect(status).toHaveAttribute('data-status', /PENDING|CONFIRMED/);
  await expect(status).toHaveAttribute('data-status', 'CONFIRMED');
  await expect(page.getByText('Stock is reserved for order')).toBeVisible();
  await expect(page.getByText(/is confirmed\./)).toBeVisible();
  expect(await stockOf(request, CONFIRM_SKU)).toBe(18);
  await expectNoSeriousViolations(page);

  await page.goto('/orders');
  await expect(page.getByRole('table')).toBeVisible();
  await expectNoSeriousViolations(page);
});

test('a synchronous out-of-stock shows the server message and a way back', async ({
  page,
  request,
}) => {
  await setStock(request, SYNC_SKU, 1);
  await addFromProductPage(page, SYNC_SKU, 5);
  await checkout(page, uniqueCustomer());

  const panel = page.getByTestId('error-panel');
  await expect(panel).toContainText(`${SYNC_SKU}: requested 5, available 1`);
  await expect(panel).toContainText(/Reference\s+\S+/);
  await panel.getByRole('link', { name: 'Back to the basket' }).click();
  await expect(page).toHaveURL(/\/basket$/);
  await expect(page.getByText('Only 1 available')).toBeVisible();
  await setStock(request, SYNC_SKU, 25);
});

test('an asynchronous rejection ends REJECTED with the reason', async ({ page, request }) => {
  test.setTimeout(150_000);
  await setStock(request, ASYNC_SKU, 3);
  await addFromProductPage(page, ASYNC_SKU, 2);
  compose('stop', 'inventory-consumer');
  try {
    await checkout(page, uniqueCustomer());
    await expect(page).toHaveURL(/\/orders\/[0-9A-Z]{26}$/);
    await expect(page.getByTestId('order-status')).toHaveAttribute('data-status', 'PENDING');
    await setStock(request, ASYNC_SKU, 0); // the stock disappears before the consumer looks
  } finally {
    compose('start', 'inventory-consumer');
  }
  await expect(page.getByTestId('order-status')).toHaveAttribute('data-status', 'REJECTED', {
    timeout: 60_000,
  });
  await expect(page.getByText('OUT_OF_STOCK').first()).toBeVisible();
  await expect(page.getByText(/could not reserve stock/)).toBeVisible();
  await expectNoSeriousViolations(page);
  await setStock(request, ASYNC_SKU, 25);
});

test('double-clicking Place order creates one order', async ({ page, request }) => {
  await setStock(request, DOUBLE_SKU, 30);
  const customer = uniqueCustomer();
  await addFromProductPage(page, DOUBLE_SKU, 1);
  await page.goto('/checkout');
  await page.getByLabel(/Customer id/).fill(customer);
  await page.getByRole('button', { name: 'Place order (demo, no payment)' }).dblclick();
  await expect(page).toHaveURL(/\/orders\/[0-9A-Z]{26}$/);
  await expect(page.getByTestId('order-status')).toHaveAttribute('data-status', 'CONFIRMED');

  const list = (await (await request.get(`/api/v1/orders?customer_id=${customer}`)).json()) as {
    total: number;
  };
  expect(list.total).toBe(1);
});

test('my orders paginates', async ({ page, request }) => {
  test.setTimeout(150_000);
  const customer = 'pw-pager';
  await setStock(request, PAGER_SKU, 500);
  // Fixed keys: a second run replays the same 21 orders instead of creating more.
  for (let i = 0; i < 21; i += 1) {
    const response = await request.post('/api/v1/orders', {
      data: { customer_id: customer, items: [{ sku: PAGER_SKU, quantity: 1 }] },
      headers: { 'Idempotency-Key': `pw-pager-${i}` },
    });
    expect([200, 202]).toContain(response.status());
  }
  await page.addInitScript((id) => {
    window.localStorage.setItem('retail.customer.v1', id);
  }, customer);
  await page.goto('/orders');
  await expect(page.getByText('Page 1 of 2')).toBeVisible();
  await expect(page.getByRole('table').getByRole('row')).toHaveCount(21); // header + 20
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Page 2 of 2')).toBeVisible();
  await expect(page.getByRole('table').getByRole('row')).toHaveCount(2); // header + 1
});

test('stopping product-service shows a retryable catalog error and recovers', async ({
  page,
  request,
}) => {
  test.setTimeout(150_000);
  compose('stop', 'product-service');
  try {
    await page.goto('/');
    const panel = page.getByTestId('error-panel');
    await expect(panel).toContainText('Could not load the catalog');
    await expect(panel).toContainText(/Reference\s+\S+/);
    await expect(panel.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expectNoSeriousViolations(page);
  } finally {
    compose('start', 'product-service');
  }
  await expect
    .poll(async () => (await request.get('/api/v1/categories')).status(), { timeout: 60_000 })
    .toBe(200);
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('list', { name: 'Products' })).toBeVisible();
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

test('demo tools are available in this local build', async ({ page, request }) => {
  await page.goto('/demo');
  await expect(page.getByRole('heading', { name: 'Demo tools' })).toBeVisible();
  await page.getByLabel('SKU').fill('SKU-SLIPPER-GRY-41');
  await page.getByLabel('Available units').fill('17');
  await page.getByRole('button', { name: 'Set stock' }).click();
  await expect(page.getByText('Stock for SKU-SLIPPER-GRY-41 is now 17')).toBeVisible();
  expect(await stockOf(request, 'SKU-SLIPPER-GRY-41')).toBe(17);
  await expectNoSeriousViolations(page);
});

test('a page at phone width has no horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  for (const path of ['/', '/basket', '/orders']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

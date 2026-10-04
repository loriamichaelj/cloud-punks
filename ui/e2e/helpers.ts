import { execFileSync } from 'node:child_process';
import AxeBuilder from '@axe-core/playwright';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const CUSTOMER_KEY = 'retail.customer.v1';

export function compose(...args: string[]): void {
  const command = process.env.E2E_COMPOSE;
  if (!command) throw new Error('E2E_COMPOSE is not set: run through `make ui-e2e`');
  const [bin, ...base] = command.split(' ');
  execFileSync(bin!, [...base, ...args], { stdio: 'pipe', timeout: 120_000 });
}

export function uniqueCustomer(name = 'pw'): string {
  return `${name}-${Math.random().toString(16).slice(2, 10)}`;
}

/** Start the browser tab as this customer (the demo customer id lives in localStorage). Only on
 * the tab's first page load, so a later switch on the demo page is not undone. */
export async function actAs(page: Page, customer: string): Promise<void> {
  await page.addInitScript(
    ([key, id]) => {
      if (window.sessionStorage.getItem('pw-acted') !== null) return;
      window.sessionStorage.setItem('pw-acted', '1');
      window.localStorage.setItem(key!, id!);
    },
    [CUSTOMER_KEY, customer],
  );
}

interface ListingBody {
  items: { seller: string; status: string }[];
}

/** Hand a CloudPunk back to the platform: end its listing (after any pending sale settles) and
 * reset its owner, so the collection is all red again for the next run. */
export async function resetPunk(request: APIRequestContext, sku: string): Promise<void> {
  await expect
    .poll(async () => {
      const body = (await (await request.get(`/api/v1/listings?sku=${sku}`)).json()) as ListingBody;
      return body.items.some((l) => l.status === 'SALE_PENDING');
    })
    .toBe(false);
  const body = (await (await request.get(`/api/v1/listings?sku=${sku}`)).json()) as ListingBody;
  for (const listing of body.items) {
    await request.delete(`/api/v1/listings/${sku}?customer_id=${listing.seller}`);
  }
  const reset = await request.put(`/api/v1/inventory/${sku}`, {
    data: { available: 1, reset_owner: true },
  });
  expect(reset.status()).toBe(200);
}

/** Buy a CloudPunk through the API as ``customer`` and wait until they own it. */
export async function buyAs(
  request: APIRequestContext,
  customer: string,
  sku: string,
): Promise<void> {
  const response = await request.post('/api/v1/orders', {
    data: { customer_id: customer, items: [{ sku, quantity: 1 }] },
    headers: { 'Idempotency-Key': `pw-${customer}-${sku}` },
  });
  expect([200, 202]).toContain(response.status());
  await expect.poll(async () => ownerOf(request, sku)).toBe(customer);
}

export async function ownerOf(request: APIRequestContext, sku: string): Promise<string | null> {
  const body = (await (await request.get(`/api/v1/inventory/${sku}`)).json()) as {
    owner: string | null;
  };
  return body.owner;
}

/** Fail on any serious or critical accessibility violation on the page as it is now. */
export async function expectNoSeriousViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual(
    [],
  );
}

export function cardFor(page: Page, sku: string) {
  return page.locator(`[data-testid="punk-card"][data-sku="${sku}"]`);
}

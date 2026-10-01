import { execFileSync } from 'node:child_process';
import AxeBuilder from '@axe-core/playwright';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

export function compose(...args: string[]): void {
  const command = process.env.E2E_COMPOSE;
  if (!command) throw new Error('E2E_COMPOSE is not set: run through `make ui-e2e`');
  const [bin, ...base] = command.split(' ');
  execFileSync(bin!, [...base, ...args], { stdio: 'pipe', timeout: 120_000 });
}

export async function setStock(request: APIRequestContext, sku: string, available: number) {
  const response = await request.put(`/api/v1/inventory/${sku}`, { data: { available } });
  expect(response.status()).toBe(200);
}

export async function stockOf(request: APIRequestContext, sku: string): Promise<number> {
  const body = (await (await request.get(`/api/v1/inventory/${sku}`)).json()) as {
    available: number;
  };
  return body.available;
}

export function uniqueCustomer(): string {
  return `pw-${Math.random().toString(16).slice(2, 10)}`;
}

/** Fail on any serious or critical accessibility violation on the page as it is now. */
export async function expectNoSeriousViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual(
    [],
  );
}

/** Add `quantity` of a product from its page, then open the basket. */
export async function addFromProductPage(page: Page, sku: string, quantity: number) {
  await page.goto(`/products/${sku}`);
  await expect(page.getByRole('heading', { level: 1 })).not.toHaveText('');
  await page.getByLabel('Quantity').fill(String(quantity));
  await page.getByRole('button', { name: 'Add to basket' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Added' })).toBeVisible();
}

export async function checkout(page: Page, customer: string) {
  await page.goto('/checkout');
  await page.getByLabel(/Customer id/).fill(customer);
  await page.getByRole('button', { name: 'Place order (demo, no payment)' }).click();
}

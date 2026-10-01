import { defineConfig, devices } from '@playwright/test';

// Journeys run against the Compose stack through the gateway (`make up seed` first, then
// `make ui-e2e`). One worker: they stop and start containers and share the seeded stock.
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], headless: true } }],
});

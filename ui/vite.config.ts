/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // `make ui-dev`: the SPA talks to the Compose stack through the gateway.
    proxy: { '/api': 'http://localhost:8080' },
  },
  // assetsInlineLimit 0: product art stays as cacheable files under /assets, not data: URIs in the JS.
  build: { sourcemap: false, target: 'es2022', assetsInlineLimit: 0 },
  css: { modules: { localsConvention: 'camelCaseOnly' } },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**'],
      thresholds: { lines: 80 },
    },
  },
});

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { server } from './server';

// Node's fetch needs absolute URLs; the app uses relative ones (same-origin in a browser).
const nativeFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = (input, init) =>
  nativeFetch(
    typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input,
    init,
  );

// jsdom has no layout, so its scrollTo only logs "not implemented"; the screens call it on every
// route change.
window.scrollTo = () => undefined;

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});

afterAll(() => {
  server.close();
});

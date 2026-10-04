import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { App } from '../App';
import { CustomerProvider } from '../state';

export function renderApp(path = '/') {
  // The same defaults as production (see main.tsx); no retries so a failure shows at once.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <CustomerProvider>
            <App />
          </CustomerProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { App } from './App';
import { BasketProvider, CustomerProvider } from './state';
import './styles/global.css';

const client = new QueryClient();
const root = document.getElementById('root');
if (!root) throw new Error('missing #root');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <CustomerProvider>
          <BasketProvider>
            <App />
          </BasketProvider>
        </CustomerProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

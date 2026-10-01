// Browser-held state: the basket and the demo customer id. Both persist through lib/ (which
// tolerates blocked storage); React state is the source of truth during a session.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import {
  addToBasket,
  loadBasket,
  removeLine,
  saveBasket,
  setQuantity,
  type AddResult,
  type BasketLine,
} from './lib/basket';
import { loadCustomerId, saveCustomerId } from './lib/customer';

interface BasketApi {
  lines: readonly BasketLine[];
  count: number;
  add: (line: BasketLine) => AddResult['error'];
  setQuantity: (sku: string, quantity: number) => void;
  remove: (sku: string) => void;
  clear: () => void;
}

interface CustomerApi {
  customerId: string;
  setCustomerId: (value: string) => boolean;
}

const BasketContext = createContext<BasketApi | null>(null);
const CustomerContext = createContext<CustomerApi | null>(null);

export function BasketProvider({ children }: { children: ReactNode }) {
  const [lines, setLines] = useState<readonly BasketLine[]>(loadBasket);

  const commit = useCallback((next: readonly BasketLine[]) => {
    setLines(next);
    saveBasket(next);
  }, []);

  const api = useMemo<BasketApi>(
    () => ({
      lines,
      count: lines.reduce((sum, l) => sum + l.quantity, 0),
      add: (line) => {
        const result = addToBasket(lines, line);
        if (!result.error) commit(result.lines);
        return result.error;
      },
      setQuantity: (sku, quantity) => {
        commit(setQuantity(lines, sku, quantity));
      },
      remove: (sku) => {
        commit(removeLine(lines, sku));
      },
      clear: () => {
        commit([]);
      },
    }),
    [lines, commit],
  );

  return <BasketContext.Provider value={api}>{children}</BasketContext.Provider>;
}

export function CustomerProvider({ children }: { children: ReactNode }) {
  const [customerId, setId] = useState(loadCustomerId);
  const api = useMemo<CustomerApi>(
    () => ({
      customerId,
      setCustomerId: (value) => {
        const trimmed = value.trim();
        if (!saveCustomerId(trimmed)) return false;
        setId(trimmed);
        return true;
      },
    }),
    [customerId],
  );
  return <CustomerContext.Provider value={api}>{children}</CustomerContext.Provider>;
}

export function useBasket(): BasketApi {
  const value = useContext(BasketContext);
  if (!value) throw new Error('useBasket needs a BasketProvider');
  return value;
}

export function useCustomer(): CustomerApi {
  const value = useContext(CustomerContext);
  if (!value) throw new Error('useCustomer needs a CustomerProvider');
  return value;
}

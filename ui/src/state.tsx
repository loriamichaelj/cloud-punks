// Browser-held state: the demo customer id, which plays the part of a wallet address (there is no
// login). It persists through lib/customer (which tolerates blocked storage); React state is the
// source of truth during a session.

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { loadCustomerId, saveCustomerId } from './lib/customer';

interface CustomerApi {
  customerId: string;
  setCustomerId: (value: string) => boolean;
}

const CustomerContext = createContext<CustomerApi | null>(null);

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

export function useCustomer(): CustomerApi {
  const value = useContext(CustomerContext);
  if (!value) throw new Error('useCustomer needs a CustomerProvider');
  return value;
}

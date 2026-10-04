// Browser-held state: the demo customer id, which plays the part of a wallet address (there is no
// login), and the customers this browser has acted as, so a tester can switch between them. Both
// persist through lib/customer (which tolerates blocked storage); React state is the source of
// truth during a session.

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import {
  isValidCustomerId,
  loadCustomerId,
  loadKnownCustomers,
  newCustomerId,
  saveCustomerId,
  saveKnownCustomers,
  withCustomer,
} from './lib/customer';

interface CustomerApi {
  customerId: string;
  /** Every customer this browser has acted as, oldest first; includes the current one. */
  customers: readonly string[];
  /** Act as this customer (remembered). False when the id is not valid. */
  setCustomerId: (value: string) => boolean;
  /** Act as a new customer named ``name``, or a generated id when blank. Null when invalid. */
  createCustomer: (name: string) => string | null;
  /** Drop a customer from the list (never the current one). Their CloudPunks stay theirs. */
  forgetCustomer: (value: string) => void;
}

const CustomerContext = createContext<CustomerApi | null>(null);

export function CustomerProvider({ children }: { children: ReactNode }) {
  const [customerId, setId] = useState(loadCustomerId);
  const [customers, setCustomers] = useState(() => loadKnownCustomers(customerId));
  const api = useMemo<CustomerApi>(() => {
    const actAs = (value: string): boolean => {
      const trimmed = value.trim();
      if (!isValidCustomerId(trimmed)) return false;
      saveCustomerId(trimmed); // best effort: with storage blocked the switch lasts the session
      const next = withCustomer(customers, trimmed);
      saveKnownCustomers(next);
      setCustomers(next);
      setId(trimmed);
      return true;
    };
    return {
      customerId,
      customers,
      setCustomerId: actAs,
      createCustomer: (name) => {
        const id = newCustomerId(name);
        return id !== null && actAs(id) ? id : null;
      },
      forgetCustomer: (value) => {
        if (value === customerId) return;
        const next = customers.filter((c) => c !== value);
        saveKnownCustomers(next);
        setCustomers(next);
      },
    };
  }, [customerId, customers]);
  return <CustomerContext.Provider value={api}>{children}</CustomerContext.Provider>;
}

export function useCustomer(): CustomerApi {
  const value = useContext(CustomerContext);
  if (!value) throw new Error('useCustomer needs a CustomerProvider');
  return value;
}

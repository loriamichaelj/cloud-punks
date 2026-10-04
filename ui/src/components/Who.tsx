import { Link } from 'react-router';
import { useCustomer } from '../state';

/** A customer id as a person reads it: "you" for the current customer, "CloudPunks" for the
 * platform (no owner, or the seller of an unsold one). */
export function Who({ id }: { id: string | null | undefined }) {
  const { customerId } = useCustomer();
  if (id === null || id === undefined) return <span>CloudPunks</span>;
  if (id === customerId) return <Link to="/account">you</Link>;
  return <span>{id}</span>;
}

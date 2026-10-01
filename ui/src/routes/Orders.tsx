import { Link, useSearchParams } from 'react-router';
import { useOrders } from '../api/hooks';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { Pagination } from '../components/Pagination';
import { Price } from '../components/Price';
import { useCustomer } from '../state';
import ui from '../styles/ui.module.css';

export function OrdersPage() {
  const { customerId } = useCustomer();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get('page')) || 1);
  const orders = useOrders(customerId, page);

  return (
    <>
      <h1>My orders</h1>
      <p className={ui.hint}>
        Showing orders for the demo customer <strong>{customerId}</strong>. You can change it at
        checkout.
      </p>
      {orders.isPending && <Loading what="your orders" />}
      {orders.isError && (
        <ErrorPanel
          error={orders.error}
          title="Could not load your orders"
          onRetry={() => {
            void orders.refetch();
          }}
        />
      )}
      {orders.data && (
        <>
          {orders.data.items.length === 0 ? (
            <p>
              No orders yet. <Link to="/">Browse the catalog</Link>.
            </p>
          ) : (
            <div className={ui.tableWrap}>
              <table className={ui.table}>
                <caption className="visually-hidden">Your orders, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Order</th>
                    <th scope="col">Placed</th>
                    <th scope="col">Status</th>
                    <th scope="col" className={ui.num}>
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {orders.data.items.map((o) => (
                    <tr key={o.order_id}>
                      <td>
                        <Link to={`/orders/${o.order_id}`}>{o.order_id}</Link>
                      </td>
                      <td>{new Date(o.created_at).toLocaleString()}</td>
                      <td>{o.status}</td>
                      <td className={ui.num}>
                        <Price value={o.total_amount} currency={o.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination
            page={orders.data.page}
            size={orders.data.size}
            total={orders.data.total}
            onPage={(p) => {
              setParams(p > 1 ? { page: String(p) } : {});
            }}
          />
        </>
      )}
    </>
  );
}

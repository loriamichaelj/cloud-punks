import { Link } from 'react-router';
import { useAvailability } from '../api/hooks';
import { ErrorPanel } from '../components/ErrorPanel';
import { ProductImage } from '../components/ProductImage';
import { QuantityInput } from '../components/QuantityInput';
import { Price, formatPrice } from '../components/Price';
import { MAX_LINES } from '../lib/basket';
import { addMinor, minorToDecimal, parseMinor, timesMinor } from '../lib/money';
import { useBasket } from '../state';
import ui from '../styles/ui.module.css';

export function estimateTotal(lines: readonly { unitPrice: string; quantity: number }[]): string {
  return minorToDecimal(
    lines.reduce((sum, l) => addMinor(sum, timesMinor(parseMinor(l.unitPrice), l.quantity)), 0n),
  );
}

export function BasketPage() {
  const basket = useBasket();
  const items = basket.lines.map((l) => ({ sku: l.sku, quantity: l.quantity }));
  const availability = useAvailability(items);
  const bySku = new Map(availability.data?.items.map((i) => [i.sku, i]));
  const problems = basket.lines.filter((l) => bySku.get(l.sku)?.sufficient === false);

  if (basket.lines.length === 0) {
    return (
      <>
        <h1>Basket</h1>
        <p>Your basket is empty.</p>
        <Link className={ui.button} to="/">
          Browse the catalog
        </Link>
      </>
    );
  }

  const currency = basket.lines[0]?.currency ?? 'USD';
  return (
    <>
      <h1>Basket</h1>
      {availability.isError && (
        <ErrorPanel
          error={availability.error}
          title="Could not check stock"
          onRetry={() => {
            void availability.refetch();
          }}
        />
      )}
      {problems.length > 0 && (
        <div role="alert" className={`${ui.alert} ${ui.alertWarn}`}>
          Some items may not be available in the quantity you want. Adjust or remove them before you
          check out.
        </div>
      )}
      <div className={ui.panel}>
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <caption className="visually-hidden">Basket lines</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col" className={ui.num}>
                  Unit price
                </th>
                <th scope="col">Quantity</th>
                <th scope="col" className={ui.num}>
                  Line total
                </th>
                <th scope="col">
                  <span className="visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {basket.lines.map((line) => {
                const check = bySku.get(line.sku);
                return (
                  <tr key={line.sku}>
                    <td>
                      <div className={ui.lineItem}>
                        <ProductImage sku={line.sku} size="thumb" />
                        <div>
                          <Link to={`/products/${encodeURIComponent(line.sku)}`}>{line.name}</Link>
                          {check && !check.sufficient && (
                            <div className={ui.fieldError} role="status">
                              {check.available <= 0
                                ? 'Out of stock'
                                : `Only ${check.available} available`}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className={ui.num}>
                      <Price value={line.unitPrice} currency={line.currency} />
                    </td>
                    <td>
                      <QuantityInput
                        id={`qty-${line.sku}`}
                        label={`Quantity for ${line.name}`}
                        value={line.quantity}
                        onChange={(q) => {
                          basket.setQuantity(line.sku, q);
                        }}
                      />
                    </td>
                    <td className={ui.num}>
                      {formatPrice(
                        minorToDecimal(timesMinor(parseMinor(line.unitPrice), line.quantity)),
                        line.currency,
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`${ui.button} ${ui.danger}`}
                        onClick={() => {
                          basket.remove(line.sku);
                        }}
                      >
                        Remove<span className="visually-hidden"> {line.name}</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p>
          <strong>Estimated total: {formatPrice(estimateTotal(basket.lines), currency)}</strong>
          <br />
          <span className={ui.hint}>
            An estimate from the prices shown. The order confirmation has the final total. Up to{' '}
            {MAX_LINES} different products per order.
          </span>
        </p>
        <div className={ui.row}>
          <Link className={ui.button} to="/checkout">
            Check out
          </Link>
          <button type="button" className={`${ui.button} ${ui.secondary}`} onClick={basket.clear}>
            Empty basket
          </button>
        </div>
      </div>
    </>
  );
}

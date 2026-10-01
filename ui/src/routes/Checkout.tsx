import { useMutation } from '@tanstack/react-query';
import { useState, type SyntheticEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api/endpoints';
import { ApiError } from '../api/client';
import { ErrorPanel } from '../components/ErrorPanel';
import { formatPrice } from '../components/Price';
import { fingerprint } from '../lib/basket';
import { newCorrelationId } from '../lib/correlation';
import { isValidCustomerId } from '../lib/customer';
import { clearAttempt, keyFor } from '../lib/idempotency';
import { useBasket, useCustomer } from '../state';
import ui from '../styles/ui.module.css';
import { estimateTotal } from './Basket';

/** SKUs named in an UNKNOWN_PRODUCT / PRODUCT_INACTIVE message that are in the basket. */
export function flaggedSkus(error: unknown, skus: readonly string[]): string[] {
  if (!(error instanceof ApiError)) return [];
  if (error.code !== 'UNKNOWN_PRODUCT' && error.code !== 'PRODUCT_INACTIVE') return [];
  return skus.filter((sku) => error.message.includes(sku));
}

export function CheckoutPage() {
  const basket = useBasket();
  const { customerId, setCustomerId } = useCustomer();
  const navigate = useNavigate();
  const [draftId, setDraftId] = useState(customerId);
  const idValid = isValidCustomerId(draftId.trim());

  const place = useMutation({
    mutationFn: () => {
      // The key is derived from the basket (and customer) and stored, so a retry, a refresh or a
      // double click sends the same key and the server creates one order.
      const key = keyFor(fingerprint(draftId.trim(), basket.lines));
      return api.createOrder(
        {
          customer_id: draftId.trim(),
          items: basket.lines.map((l) => ({ sku: l.sku, quantity: l.quantity })),
        },
        key,
        { correlationId: newCorrelationId() },
      );
    },
    onSuccess: (order) => {
      clearAttempt();
      basket.clear();
      void navigate(`/orders/${order.order_id}`);
    },
  });

  if (basket.lines.length === 0 && !place.isSuccess) {
    return (
      <>
        <h1>Checkout</h1>
        <p>Your basket is empty.</p>
        <Link className={ui.button} to="/">
          Browse the catalog
        </Link>
      </>
    );
  }

  const flagged = flaggedSkus(
    place.error,
    basket.lines.map((l) => l.sku),
  );
  const currency = basket.lines[0]?.currency ?? 'USD';
  const outOfStock = place.error instanceof ApiError && place.error.code === 'OUT_OF_STOCK';

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (!idValid || place.isPending) return;
    setCustomerId(draftId);
    place.mutate();
  };

  return (
    <>
      <h1>Checkout</h1>
      {place.isError && (
        <ErrorPanel
          error={place.error}
          title={outOfStock ? 'Some items are out of stock' : 'Could not place the order'}
          {...(outOfStock
            ? {}
            : {
                onRetry: () => {
                  place.mutate();
                },
              })}
        >
          {(outOfStock || flagged.length > 0) && <Link to="/basket">Back to the basket</Link>}
        </ErrorPanel>
      )}

      <form className={ui.panel} onSubmit={submit} noValidate>
        <div className={ui.field}>
          <label htmlFor="customer-id">Customer id (a demo label, not a login)</label>
          <input
            id="customer-id"
            className={ui.input}
            value={draftId}
            aria-invalid={!idValid}
            aria-describedby="customer-hint"
            onChange={(e) => {
              setDraftId(e.target.value);
            }}
          />
          <span id="customer-hint" className={idValid ? ui.hint : ui.fieldError}>
            Letters, digits, dot, dash, underscore or colon; up to 64 characters.
          </span>
        </div>

        <h2>Your order</h2>
        <ul>
          {basket.lines.map((l) => (
            <li key={l.sku}>
              {l.quantity} × {l.name} at {formatPrice(l.unitPrice, l.currency)}
              {flagged.includes(l.sku) && (
                <strong className={ui.fieldError}> (no longer available)</strong>
              )}
            </li>
          ))}
        </ul>
        <p>
          <strong>Estimated total: {formatPrice(estimateTotal(basket.lines), currency)}</strong>
          <br />
          <span className={ui.hint}>
            An estimate. The confirmation shows the final total, priced by the server.
          </span>
        </p>
        <button type="submit" className={ui.button} disabled={!idValid || place.isPending}>
          {place.isPending ? 'Placing order…' : 'Place order (demo, no payment)'}
        </button>
        <p className={ui.hint}>No payment is taken. This is a demonstration.</p>
      </form>
    </>
  );
}

import { useState, type SyntheticEvent } from 'react';
import { Link, useParams } from 'react-router';
import { useProduct, useStock } from '../api/hooks';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { Price } from '../components/Price';
import { ProductAvatar } from '../components/ProductAvatar';
import { StockBadge } from '../components/StockBadge';
import { MAX_QUANTITY } from '../lib/basket';
import { useBasket } from '../state';
import ui from '../styles/ui.module.css';

export function ProductPage() {
  const { sku = '' } = useParams();
  const product = useProduct(sku);
  const stock = useStock(sku);
  const basket = useBasket();
  const [quantity, setQuantity] = useState('1');
  const [message, setMessage] = useState('');

  if (product.isPending) return <Loading what="the product" />;
  if (product.isError) {
    return (
      <ErrorPanel
        error={product.error}
        title="Could not load this product"
        onRetry={() => {
          void product.refetch();
        }}
      >
        <Link to="/">Back to the catalog</Link>
      </ErrorPanel>
    );
  }

  const p = product.data;
  const available = stock.data?.available;
  const outOfStock = available !== undefined && available <= 0;
  const parsed = Number(quantity);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= MAX_QUANTITY;

  const onSubmit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (!valid) return;
    const error = basket.add({
      sku: p.sku,
      name: p.name,
      unitPrice: p.price,
      currency: p.currency,
      quantity: parsed,
    });
    setMessage(
      error === 'basket-full'
        ? 'Your basket already has 20 different products. Remove one first.'
        : `Added ${parsed} to your basket.`,
    );
  };

  return (
    <>
      <p>
        <Link to="/">← Catalog</Link>
      </p>
      <h1>{p.name}</h1>
      <div className={ui.panel}>
        <ProductAvatar name={p.name} />
        <p>{p.description ?? 'No description.'}</p>
        <p>
          <strong>
            <Price value={p.price} currency={p.currency} />
          </strong>{' '}
          {available !== undefined && <StockBadge available={available} />}
        </p>
        {stock.isError && (
          <p className={`${ui.alert} ${ui.alertWarn}`}>Stock level unavailable right now.</p>
        )}
        <form onSubmit={onSubmit} noValidate>
          <div className={ui.field}>
            <label htmlFor="quantity">Quantity</label>
            <input
              id="quantity"
              className={ui.input}
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_QUANTITY}
              value={quantity}
              aria-invalid={!valid}
              aria-describedby="quantity-hint"
              onChange={(e) => {
                setQuantity(e.target.value);
              }}
            />
            <span id="quantity-hint" className={valid ? ui.hint : ui.fieldError}>
              Between 1 and {MAX_QUANTITY}.
            </span>
          </div>
          <button type="submit" className={ui.button} disabled={outOfStock || !valid}>
            Add to basket
          </button>
        </form>
        <p role="status" aria-live="polite">
          {message} {message.startsWith('Added') && <Link to="/basket">View basket</Link>}
        </p>
      </div>
    </>
  );
}

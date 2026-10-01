// Exists only in builds with VITE_DEMO_TOOLS=true. These call the unauthenticated admin
// endpoints (PUT /inventory/{sku}, PUT /products/{sku}) so that "out of stock" and an async
// REJECTED order can be demonstrated by hand. Never enabled in a cloud build.

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type SyntheticEvent } from 'react';
import { api } from '../api/endpoints';
import { ErrorPanel } from '../components/ErrorPanel';
import ui from '../styles/ui.module.css';

const SKU = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const PRICE = /^\d{1,8}(\.\d{1,2})?$/;

export function DemoPage() {
  const client = useQueryClient();
  const [sku, setSku] = useState('');
  const [available, setAvailable] = useState('0');
  const [price, setPrice] = useState('');
  const [done, setDone] = useState('');

  const skuOk = SKU.test(sku);
  const availableOk = /^\d{1,7}$/.test(available);
  const priceOk = PRICE.test(price);

  const stock = useMutation({
    mutationFn: () => api.setStock(sku, Number(available)),
    onSuccess: (s) => {
      setDone(`Stock for ${s.sku} is now ${s.available} available, ${s.reserved} reserved.`);
      void client.invalidateQueries({ queryKey: ['stock'] });
    },
  });

  const reprice = useMutation({
    mutationFn: async () => {
      const current = await api.product(sku);
      // PUT replaces every mutable field, so send the rest back unchanged.
      return api.updateProduct(sku, {
        name: current.name,
        description: current.description,
        category: current.category,
        currency: current.currency,
        active: current.active,
        price,
      });
    },
    onSuccess: (p) => {
      setDone(`Price of ${p.sku} is now ${p.price}. Catalog pages may show it for up to a minute.`);
      void client.invalidateQueries({ queryKey: ['product'] });
    },
  });

  const onStock = (e: SyntheticEvent) => {
    e.preventDefault();
    if (skuOk && availableOk) stock.mutate();
  };
  const onPrice = (e: SyntheticEvent) => {
    e.preventDefault();
    if (skuOk && priceOk) reprice.mutate();
  };

  return (
    <>
      <h1>Demo tools</h1>
      <p className={`${ui.alert} ${ui.alertWarn}`}>
        These call unauthenticated admin endpoints. They exist only in local builds.
      </p>
      <p role="status" aria-live="polite">
        {done}
      </p>
      <div className={ui.field}>
        <label htmlFor="demo-sku">SKU</label>
        <input
          id="demo-sku"
          className={ui.input}
          value={sku}
          onChange={(e) => {
            setSku(e.target.value);
          }}
        />
      </div>

      <form className={ui.panel} onSubmit={onStock} noValidate>
        <h2>Set stock</h2>
        <div className={ui.field}>
          <label htmlFor="demo-available">Available units</label>
          <input
            id="demo-available"
            className={ui.input}
            inputMode="numeric"
            value={available}
            onChange={(e) => {
              setAvailable(e.target.value);
            }}
          />
        </div>
        <button
          type="submit"
          className={ui.button}
          disabled={!skuOk || !availableOk || stock.isPending}
        >
          Set stock
        </button>
        {stock.isError && <ErrorPanel error={stock.error} title="Could not set the stock" />}
      </form>

      <form className={ui.panel} onSubmit={onPrice} noValidate>
        <h2>Set price</h2>
        <div className={ui.field}>
          <label htmlFor="demo-price">New price (e.g. 19.99)</label>
          <input
            id="demo-price"
            className={ui.input}
            inputMode="decimal"
            value={price}
            onChange={(e) => {
              setPrice(e.target.value);
            }}
          />
        </div>
        <button
          type="submit"
          className={ui.button}
          disabled={!skuOk || !priceOk || reprice.isPending}
        >
          Set price
        </button>
        {reprice.isError && <ErrorPanel error={reprice.error} title="Could not set the price" />}
      </form>
    </>
  );
}

import { Link, useSearchParams } from 'react-router';
import { useAvailability, useCategories, useProducts } from '../api/hooks';
import type { Product } from '../api/types';
import { ErrorPanel } from '../components/ErrorPanel';
import { Loading } from '../components/Loading';
import { Pagination } from '../components/Pagination';
import { Price } from '../components/Price';
import { ProductAvatar } from '../components/ProductAvatar';
import { StockBadge } from '../components/StockBadge';
import { useBasket } from '../state';
import ui from '../styles/ui.module.css';
import styles from './catalog.module.css';

const PAGE_SIZE = 20;

export function Catalog() {
  const [params, setParams] = useSearchParams();
  const category = params.get('category') ?? undefined;
  const page = Math.max(1, Number(params.get('page')) || 1);

  const categories = useCategories();
  const products = useProducts(category, page);
  const items = products.data?.items ?? [];

  // One availability call for the whole page (at most 20 lines: the endpoint's cap).
  const availability = useAvailability(items.map((p) => ({ sku: p.sku, quantity: 1 })));
  const stockBySku = new Map(availability.data?.items.map((line) => [line.sku, line.available]));

  const update = (next: { category?: string | undefined; page?: number }) => {
    const search = new URLSearchParams();
    const nextCategory = 'category' in next ? next.category : category;
    if (nextCategory) search.set('category', nextCategory);
    if ((next.page ?? 1) > 1) search.set('page', String(next.page));
    setParams(search);
  };

  return (
    <>
      <h1>Catalog</h1>

      <div className={styles.filters} role="group" aria-label="Filter by category">
        <button
          type="button"
          className={`${ui.button} ${category ? ui.secondary : ''}`}
          aria-pressed={!category}
          onClick={() => {
            update({ category: undefined });
          }}
        >
          All
        </button>
        {categories.data?.items.map((c) => (
          <button
            key={c.slug}
            type="button"
            className={`${ui.button} ${category === c.slug ? '' : ui.secondary}`}
            aria-pressed={category === c.slug}
            onClick={() => {
              update({ category: c.slug });
            }}
          >
            {c.name}
          </button>
        ))}
      </div>
      {categories.isError && (
        <p className={ui.hint}>The category filter is unavailable right now.</p>
      )}

      {products.isPending && <Loading what="products" />}
      {products.isError && (
        <ErrorPanel
          error={products.error}
          title="Could not load the catalog"
          onRetry={() => {
            void products.refetch();
          }}
        />
      )}

      {products.data && (
        <>
          {availability.isError && (
            <p className={`${ui.alert} ${ui.alertWarn}`} role="status">
              Stock levels are unavailable right now, so every product is shown without a stock
              badge.
            </p>
          )}
          {items.length === 0 ? (
            <p>No products in this category.</p>
          ) : (
            <ul className={styles.grid} aria-label="Products">
              {items.map((product) => (
                <ProductCard
                  key={product.sku}
                  product={product}
                  available={stockBySku.get(product.sku)}
                />
              ))}
            </ul>
          )}
          <Pagination
            page={products.data.page}
            size={PAGE_SIZE}
            total={products.data.total}
            onPage={(p) => {
              update({ page: p });
            }}
          />
        </>
      )}
    </>
  );
}

function ProductCard({ product, available }: { product: Product; available: number | undefined }) {
  const basket = useBasket();
  const outOfStock = available !== undefined && available <= 0;
  return (
    <li className={styles.card}>
      <ProductAvatar name={product.name} />
      <h2 className={styles.cardTitle}>
        <Link to={`/products/${encodeURIComponent(product.sku)}`}>{product.name}</Link>
      </h2>
      <div className={styles.price}>
        <Price value={product.price} currency={product.currency} />
      </div>
      <div>{available !== undefined && <StockBadge available={available} />}</div>
      <div className={styles.actions}>
        <button
          type="button"
          className={ui.button}
          disabled={outOfStock}
          onClick={() => {
            basket.add({
              sku: product.sku,
              name: product.name,
              unitPrice: product.price,
              currency: product.currency,
              quantity: 1,
            });
          }}
        >
          Add to basket<span className="visually-hidden">: {product.name}</span>
        </button>
      </div>
    </li>
  );
}

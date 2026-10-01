import { artFor, categoryFor } from '../assets/productArt';
import { CategoryIcon } from './CategoryIcon';
import styles from '../styles/art.module.css';

type Size = 'card' | 'large' | 'thumb';

/**
 * A product's picture on a tinted tile. Decorative: the name is always next to it, so the image
 * has an empty alt and is hidden from assistive technology.
 */
export function ProductImage({
  sku,
  category,
  size = 'card',
}: {
  sku: string;
  category?: string | undefined;
  size?: Size;
}) {
  const art = artFor(sku);
  const slug = categoryFor(sku, category);
  return (
    <div className={`${styles.tile} ${styles[size]}`} data-category={slug} aria-hidden="true">
      {art ? (
        <img className={styles.art} src={art} alt="" loading="lazy" decoding="async" />
      ) : (
        <span className={styles.fallback}>
          <CategoryIcon slug={slug} size={size === 'thumb' ? 22 : 56} />
        </span>
      )}
    </div>
  );
}

export function CategoryChip({ slug, name }: { slug: string | undefined; name?: string }) {
  if (!slug) return null;
  return (
    <span className={styles.chip} data-category={slug}>
      <CategoryIcon slug={slug} size={14} />
      {name ?? slug}
    </span>
  );
}

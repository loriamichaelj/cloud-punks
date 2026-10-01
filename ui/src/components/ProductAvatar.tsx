import styles from '../routes/catalog.module.css';

/** The catalog has no images (no external requests): initials on a neutral tile. */
export function ProductAvatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join('');
  return (
    <div className={styles.avatar} aria-hidden="true">
      {initials}
    </div>
  );
}

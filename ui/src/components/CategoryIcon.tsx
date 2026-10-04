import { isKnownCategory } from '../assets/productArt';

// One head silhouette for the five types; the tile's colour tells them apart.
const HEAD = 'M8 21v-4q-3-1-3-5V8a7 7 0 0 1 14 0v4q0 3-2 4v5 M9 11h.01 M15 11h.01';
const PATHS: Record<string, string> = {
  male: HEAD,
  female: HEAD,
  zombie: HEAD,
  ape: HEAD,
  alien: HEAD,
  other: 'M3 12 12 3h9v9l-9 9-9-9Z M16 8h.01',
};

/** A small outline icon that takes its colour from the text around it. Decorative. */
export function CategoryIcon({ slug, size = 20 }: { slug: string | undefined; size?: number }) {
  const path = PATHS[isKnownCategory(slug) ? slug : 'other'];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={path} />
    </svg>
  );
}

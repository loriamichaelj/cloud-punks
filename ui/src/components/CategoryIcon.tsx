import { isKnownCategory } from '../assets/productArt';

const PATHS: Record<string, string> = {
  apparel: 'M8 3 3 6l2 4 3-1v12h8V9l3 1 2-4-5-3q-2 3-4 3T8 3Z',
  footwear: 'M3 17v-5l5-1 3-3 3 3q5 1 7 4v2H3Z M8 11l2 2 M11 8l2 3',
  accessories: 'M5 8h14l1 13H4L5 8Z M9 8V6a3 3 0 0 1 6 0v2',
  home: 'M3 11 12 4l9 7v9H3v-9Z M10 20v-5h4v5',
  electronics: 'M13 2 5 14h6l-1 8 9-13h-6l0-7Z',
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

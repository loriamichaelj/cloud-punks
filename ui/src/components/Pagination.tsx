import ui from '../styles/ui.module.css';

interface Props {
  page: number;
  size: number;
  total: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, size, total, onPage }: Props) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pagination" className={ui.row}>
      <button
        type="button"
        className={`${ui.button} ${ui.secondary}`}
        disabled={page <= 1}
        onClick={() => {
          onPage(page - 1);
        }}
      >
        Previous
      </button>
      <span aria-live="polite">
        Page {page} of {pages}
      </span>
      <button
        type="button"
        className={`${ui.button} ${ui.secondary}`}
        disabled={page >= pages}
        onClick={() => {
          onPage(page + 1);
        }}
      >
        Next
      </button>
    </nav>
  );
}

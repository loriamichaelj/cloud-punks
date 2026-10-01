import ui from '../styles/ui.module.css';

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className={ui.muted}>
      Loading {what}…
    </p>
  );
}

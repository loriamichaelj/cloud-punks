import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, NetworkError } from '../api/client';
import ui from '../styles/ui.module.css';

interface Props {
  error: unknown;
  /** A short sentence for what was being attempted, e.g. "Could not load the catalog". */
  title: string;
  onRetry?: () => void;
  children?: ReactNode;
}

/** One panel for every failure: the server's message, the correlation id with a copy button, and
 * a retry. A network failure reads differently from an API error. Never shows a stack trace. */
export function ErrorPanel({ error, title, onRetry, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  const network = error instanceof NetworkError;
  const message = network
    ? 'The server could not be reached. Check your connection and try again.'
    : error instanceof ApiError
      ? error.message
      : 'Something went wrong.';

  // Focus once per distinct failure (a refetch that fails the same way again is a new error object,
  // not a new failure), and without scrolling: role="alert" already announces it, and a page that
  // jumps to a panel below the fold slides its top under the sticky header.
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
  }, [title, message]);
  const correlationId =
    error instanceof ApiError || error instanceof NetworkError ? error.correlationId : null;

  const copy = () => {
    if (correlationId === null) return;
    navigator.clipboard
      .writeText(correlationId)
      .then(() => {
        setCopied(true);
      })
      .catch(() => {
        setCopied(false);
      });
  };

  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="alert"
      className={`${ui.alert} ${ui.alertError}`}
      data-testid="error-panel"
    >
      <p>
        <strong>{title}.</strong> {message}
      </p>
      {network && <p className={ui.hint}>This is a connection problem, not a server error.</p>}
      {correlationId !== null && (
        <p>
          Reference <span className={ui.correlation}>{correlationId}</span>{' '}
          <button type="button" className={`${ui.button} ${ui.secondary}`} onClick={copy}>
            {copied ? 'Copied' : 'Copy reference'}
          </button>
        </p>
      )}
      <div className={ui.row}>
        {onRetry && (
          <button type="button" className={ui.button} onClick={onRetry}>
            Try again
          </button>
        )}
        {children}
      </div>
    </div>
  );
}

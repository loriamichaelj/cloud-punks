import { useEffect, useRef, useState, type SyntheticEvent } from 'react';
import { Link } from 'react-router';
import { useCustomer } from '../state';
import layout from '../styles/layout.module.css';
import ui from '../styles/ui.module.css';

/** The customer pill in the header, opening a menu to switch between the customers this browser
 * has acted as, or create a new one: buy as one, put it up for bid, bid as another, accept as the
 * first. There is no login; a customer id is a label, never a credential. */
export function CustomerMenu() {
  const { customerId, customers, setCustomerId, createCustomer, forgetCustomer } = useCustomer();
  const menu = useRef<HTMLDetailsElement>(null);
  const summary = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');

  const close = (refocus: boolean) => {
    if (menu.current) menu.current.open = false;
    if (refocus) summary.current?.focus();
  };

  // Escape or a click outside closes it, as people expect of a menu.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close(true);
    };
    const onPointer = (event: PointerEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) close(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  const actAs = (id: string) => {
    if (id !== customerId && setCustomerId(id)) setAnnouncement(`You are now ${id}.`);
    close(true);
  };

  const create = (event: SyntheticEvent) => {
    event.preventDefault();
    const id = createCustomer(name);
    if (id === null) {
      setError('Use letters, digits and . _ : - (up to 64), starting with a letter or digit.');
      return;
    }
    setError(null);
    setName('');
    setAnnouncement(`You are now ${id}.`);
    close(true);
  };

  return (
    <>
      <details
        ref={menu}
        className={layout.customerMenu}
        onToggle={() => {
          setOpen(menu.current?.open ?? false);
        }}
      >
        <summary
          ref={summary}
          className={layout.wallet}
          aria-label={`Customer ${customerId}: switch or create a customer`}
          data-testid="customer-menu"
        >
          <span aria-hidden="true" className={layout.walletDot} />
          {customerId}
        </summary>
        <div className={layout.menuPanel}>
          <p className={ui.hint}>
            Acting as <strong>{customerId}</strong>. No login: a customer id is a label.
          </p>
          <Link
            to="/account"
            className={layout.menuLink}
            onClick={() => {
              close(false);
            }}
          >
            My CloudPunks
          </Link>
          <h2 className={layout.menuHeading}>Switch customer</h2>
          <ul className={layout.customerList}>
            {customers.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  className={layout.customerButton}
                  aria-current={id === customerId ? 'true' : undefined}
                  onClick={() => {
                    actAs(id);
                  }}
                >
                  <span aria-hidden="true" className={layout.walletDot} />
                  {id}
                  {id === customerId ? <span className={ui.hint}> (you)</span> : null}
                </button>
                {id !== customerId && (
                  <button
                    type="button"
                    className={layout.forget}
                    aria-label={`Forget ${id}`}
                    title="Forget (their CloudPunks stay theirs)"
                    onClick={() => {
                      forgetCustomer(id);
                    }}
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
          <form onSubmit={create} noValidate className={layout.newCustomer}>
            <label htmlFor="new-customer">New customer</label>
            <div className={ui.row}>
              <input
                id="new-customer"
                className={ui.input}
                placeholder="Name (optional)"
                autoComplete="off"
                value={name}
                aria-invalid={error !== null}
                aria-describedby={error ? 'new-customer-error' : undefined}
                onChange={(e) => {
                  setName(e.target.value);
                }}
              />
              <button type="submit" className={ui.button}>
                Create
              </button>
            </div>
            {error && (
              <p id="new-customer-error" className={ui.fieldError}>
                {error}
              </p>
            )}
          </form>
        </div>
      </details>
      {/* outside the details: its closed content is not rendered, so it would never be read */}
      <span className="visually-hidden" role="status">
        {announcement}
      </span>
    </>
  );
}

import { useState, type SyntheticEvent } from 'react';
import { Link } from 'react-router';
import { generateCustomerId, isValidCustomerId } from '../lib/customer';
import { useCustomer } from '../state';
import ui from '../styles/ui.module.css';

const PRESETS = ['cust-alice', 'cust-bob'];

/** Local builds only (VITE_DEMO_TOOLS): act as another customer, to show a resale end to end in
 * one browser. Buy as Alice, put it up for bid, switch to Bob and bid, switch back and accept. */
export function DemoPage() {
  const { customerId, setCustomerId } = useCustomer();
  const [value, setValue] = useState(customerId);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const switchTo = (id: string) => {
    if (!isValidCustomerId(id) || !setCustomerId(id)) {
      setError(
        'Use letters, digits and . _ : - (up to 64 characters), starting with a letter or digit.',
      );
      return;
    }
    setError(null);
    setValue(id);
    setMessage(`You are now ${id}.`);
  };

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    switchTo(value.trim());
  };

  return (
    <div className={ui.panel}>
      <h1>Demo tools</h1>
      <p className={ui.muted}>
        There is no login: your customer id is a label that plays the part of a wallet address.
        Switch it to act as someone else. This page exists only in local builds.
      </p>
      <form onSubmit={submit} noValidate>
        <div className={ui.field}>
          <label htmlFor="customer-id">Customer id</label>
          <input
            id="customer-id"
            className={ui.input}
            value={value}
            aria-invalid={error !== null}
            aria-describedby={error ? 'customer-error' : undefined}
            onChange={(e) => {
              setValue(e.target.value);
            }}
          />
          {error && (
            <p id="customer-error" className={ui.fieldError}>
              {error}
            </p>
          )}
        </div>
        <div className={ui.row}>
          <button type="submit" className={ui.button}>
            Switch customer
          </button>
          {PRESETS.map((id) => (
            <button
              key={id}
              type="button"
              className={`${ui.button} ${ui.secondary}`}
              onClick={() => {
                switchTo(id);
              }}
            >
              Be {id}
            </button>
          ))}
          <button
            type="button"
            className={`${ui.button} ${ui.secondary}`}
            onClick={() => {
              switchTo(generateCustomerId());
            }}
          >
            New customer
          </button>
        </div>
      </form>
      {message && (
        <p role="status" className={`${ui.alert} ${ui.alertOk}`}>
          {message} <Link to="/account">See your CloudPunks</Link>
        </p>
      )}
    </div>
  );
}

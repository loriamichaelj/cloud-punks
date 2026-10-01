import { useState } from 'react';
import { MAX_QUANTITY } from '../lib/basket';
import ui from '../styles/ui.module.css';

interface Props {
  id: string;
  label: string;
  value: number;
  onChange: (quantity: number) => void;
}

/** A number field that lets the user clear it while typing. Only a whole number from 1 to 100 is
 * committed; on blur the field shows the committed value again. */
export function QuantityInput({ id, label, value, onChange }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <>
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <input
        id={id}
        className={ui.input}
        type="number"
        inputMode="numeric"
        min={1}
        max={MAX_QUANTITY}
        value={draft ?? String(value)}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Number(e.target.value);
          if (Number.isInteger(n) && n >= 1 && n <= MAX_QUANTITY) onChange(n);
        }}
        onBlur={() => {
          setDraft(null);
        }}
      />
    </>
  );
}

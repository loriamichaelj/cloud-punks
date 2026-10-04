import { STATE_LABEL, type MarketState } from '../lib/collection';
import ui from '../styles/ui.module.css';
import art from '../styles/art.module.css';

/** The market state in words and colour (colour is never the only signal). */
export function StatePill({ state }: { state: MarketState }) {
  return (
    <span className={`${ui.pill} ${ui.statePill}`} data-state={state}>
      {STATE_LABEL[state]}
    </span>
  );
}

const MEANING: Record<MarketState, string> = {
  unsold: 'buy now from CloudPunks',
  bid: 'up for bid by its owner',
  owned: 'owned, not for sale',
};

/** Red, purple, blue: what each tile colour means. */
export function StateLegend() {
  return (
    <ul className={art.legend} aria-label="What the colours mean">
      {(['unsold', 'bid', 'owned'] as const).map((state) => (
        <li key={state} data-state={state}>
          <span className={art.swatch} aria-hidden="true" />
          <strong>{STATE_LABEL[state]}</strong> {MEANING[state]}
        </li>
      ))}
    </ul>
  );
}

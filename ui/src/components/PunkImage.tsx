import { artFor } from '../assets/cloudpunkArt';
import type { MarketState } from '../lib/collection';
import art from '../styles/art.module.css';

type Size = 'card' | 'large' | 'thumb' | 'mini';

/**
 * A CloudPunk on a tile coloured by its market state (DESIGN.md 16.1), scaled with crisp pixels.
 * Decorative: the name is always next to it, so the image has an empty alt.
 */
export function PunkImage({
  sku,
  state,
  size = 'card',
}: {
  sku: string;
  state: MarketState | undefined;
  size?: Size;
}) {
  const src = artFor(sku);
  return (
    <div className={`${art.tile} ${art[size]}`} data-state={state} aria-hidden="true">
      {src ? <img className={art.art} src={src} alt="" loading="lazy" decoding="async" /> : null}
    </div>
  );
}

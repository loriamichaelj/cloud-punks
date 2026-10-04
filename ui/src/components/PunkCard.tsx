import { Link } from 'react-router';
import { formatPrice } from './Price';
import { PunkImage } from './PunkImage';
import { Who } from './Who';
import type { CloudPunk } from '../lib/collection';
import card from '../styles/card.module.css';
import ui from '../styles/ui.module.css';

function itemPath(punk: CloudPunk): string {
  return `/cloudpunks/${String(punk.number).padStart(4, '0')}`;
}

/** One CloudPunk in the grid: the art on its state colour, its name and what it costs or who has
 * it. An unsold one offers "Buy now", which opens its page at the confirm step. */
export function PunkCard({ punk }: { punk: CloudPunk }) {
  return (
    <li className={card.card} data-state={punk.state} data-testid="punk-card" data-sku={punk.sku}>
      <Link to={itemPath(punk)} className={card.link}>
        <PunkImage sku={punk.sku} state={punk.state} />
        <span className={card.body}>
          <span className={card.name}>{punk.name}</span>
          {punk.state === 'unsold' && (
            <span className={card.price}>{formatPrice(punk.price, punk.currency)}</span>
          )}
          {punk.state === 'bid' && <span className={card.price}>Up for bid</span>}
          {punk.state === 'owned' && <span className={card.price}>Not for sale</span>}
          <span className={card.meta}>
            {punk.lastSale
              ? `Last sale ${formatPrice(punk.lastSale.amount, punk.lastSale.currency)}`
              : punk.typeName}
          </span>
        </span>
      </Link>
      {punk.state === 'unsold' ? (
        <Link
          to={`${itemPath(punk)}?buy=1`}
          className={`${ui.button} ${card.action}`}
          aria-label={`Buy now ${punk.name}`}
        >
          Buy now
        </Link>
      ) : (
        <p className={card.owner}>
          {punk.state === 'bid' ? 'Listed by ' : 'Owned by '}
          <Who id={punk.owner} />
        </p>
      )}
    </li>
  );
}

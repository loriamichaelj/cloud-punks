import { useEffect, useRef, useState, type SyntheticEvent } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router';
import { artFor } from '../assets/cloudpunkArt';
import { DEMO_TOOLS } from '../config';
import { parseNumber } from '../lib/collection';
import { useCustomer } from '../state';
import layout from '../styles/layout.module.css';
import { StateLegend } from './StatePill';

export function Layout() {
  const { customerId } = useCustomer();
  const location = useLocation();
  const navigate = useNavigate();
  const main = useRef<HTMLElement>(null);
  const [query, setQuery] = useState('');

  // Move focus to the page on every route change so keyboard and screen-reader users start at the
  // top of the new screen instead of on a link that no longer exists.
  useEffect(() => {
    main.current?.focus();
  }, [location.pathname]);

  const search = (event: SyntheticEvent) => {
    event.preventDefault();
    const text = query.trim();
    const number = parseNumber(text);
    if (number !== null) {
      void navigate(`/cloudpunks/${String(number).padStart(4, '0')}`);
    } else {
      void navigate(text ? `/?q=${encodeURIComponent(text)}` : '/');
    }
    setQuery('');
  };

  return (
    <div className={layout.shell}>
      <a className={layout.skip} href="#main">
        Skip to content
      </a>
      <header className={layout.header}>
        <div className={layout.headerInner}>
          <NavLink to="/" className={layout.brand}>
            <span className={layout.mark} aria-hidden="true">
              <img src={artFor('CP-0001')} alt="" />
            </span>
            CloudPunks
          </NavLink>
          <form role="search" className={layout.search} onSubmit={search}>
            <label htmlFor="site-search" className="visually-hidden">
              Search CloudPunks by number or trait
            </label>
            <input
              id="site-search"
              className={layout.searchInput}
              type="search"
              placeholder="Search by number or trait"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
              }}
            />
          </form>
          <nav aria-label="Main" className={layout.nav}>
            <NavLink to="/" end>
              Collection
            </NavLink>
            <NavLink to="/activity">Activity</NavLink>
            {DEMO_TOOLS && <NavLink to="/demo">Demo</NavLink>}
            <NavLink
              to="/account"
              className={layout.wallet}
              aria-label={`My CloudPunks (${customerId})`}
            >
              <span aria-hidden="true" className={layout.walletDot} />
              {customerId}
            </NavLink>
          </nav>
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1} className={layout.main}>
        <Outlet />
      </main>
      <footer className={layout.footer}>
        <StateLegend />
        <span>
          A proof of concept: no blockchain, no login and no payments. Your customer id is a label,
          not a wallet or a credential.
        </span>
      </footer>
    </div>
  );
}

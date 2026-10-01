import { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';
import { DEMO_TOOLS } from '../config';
import { useBasket } from '../state';
import layout from '../styles/layout.module.css';

export function Layout() {
  const { count } = useBasket();
  const location = useLocation();
  const main = useRef<HTMLElement>(null);

  // Move focus to the page on every route change so keyboard and screen-reader users start at the
  // top of the new screen instead of on a link that no longer exists.
  useEffect(() => {
    main.current?.focus();
  }, [location.pathname]);

  return (
    <div className={layout.shell}>
      <a className={layout.skip} href="#main">
        Skip to content
      </a>
      <header className={layout.header}>
        <div className={layout.headerInner}>
          <NavLink to="/" className={layout.brand}>
            Retail demo shop
          </NavLink>
          <nav aria-label="Main" className={layout.nav}>
            <NavLink to="/" end>
              Catalog
            </NavLink>
            <NavLink to="/basket">Basket ({count})</NavLink>
            <NavLink to="/orders" end>
              My orders
            </NavLink>
            {DEMO_TOOLS && <NavLink to="/demo">Demo tools</NavLink>}
          </nav>
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1} className={layout.main}>
        <Outlet />
      </main>
      <footer className={layout.footer}>
        Demo only: no login and no payments. Your customer id is a label, not a credential.
      </footer>
    </div>
  );
}

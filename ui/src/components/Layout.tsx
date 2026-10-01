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
            <span className={layout.mark} aria-hidden="true">
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                focusable="false"
              >
                <path d="M5 8h14l1 13H4L5 8Z" />
                <path d="M9 8V6a3 3 0 0 1 6 0v2" />
              </svg>
            </span>
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
        <span className={layout.dots} aria-hidden="true">
          <i data-category="apparel" />
          <i data-category="footwear" />
          <i data-category="accessories" />
          <i data-category="home" />
          <i data-category="electronics" />
        </span>
        <span>
          Demo only: no login and no payments. Your customer id is a label, not a credential.
        </span>
      </footer>
    </div>
  );
}

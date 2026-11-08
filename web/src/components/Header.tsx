import { useState } from "react";

export type View = "ask" | "equipment";

const LINKS: { view: View; href: string; label: string }[] = [
  { view: "ask", href: "#/", label: "Ask" },
  { view: "equipment", href: "#/equipment", label: "Equipment" },
];

/** Logo (web/public/umkc-logo.png; text if missing), product name, page links and event tag. */
export function Header({ view }: { view: View }) {
  const [logo, setLogo] = useState(true);
  return (
    <header className="site-header">
      <div className="site-header__brand">
        {logo ? (
          <img src="/umkc-logo.png" alt="UMKC" className="site-header__logo" onError={() => setLogo(false)} />
        ) : (
          <span className="site-header__wordmark">UMKC</span>
        )}
        <span className="site-header__divider" aria-hidden="true" />
        <div>
          <p className="site-header__name">Equipment Finder</p>
          <p className="site-header__tagline">Research equipment on campus, matched to your question</p>
        </div>
      </div>
      <div className="site-header__end">
        <nav className="site-nav" aria-label="Pages">
          {LINKS.map((link) => (
            <a
              key={link.view}
              href={link.href}
              className={`site-nav__link${view === link.view ? " is-active" : ""}`}
              aria-current={view === link.view ? "page" : undefined}
            >
              {link.label}
            </a>
          ))}
        </nav>
        <span className="mono site-header__event">HACK-A-ROO 2026</span>
      </div>
    </header>
  );
}

export function Footer({ note }: { note: string }) {
  return (
    <footer className="site-footer">
      <p>Built for Hack-A-Roo 2026 at UMKC. Not an official university service.</p>
      {note && <p>{note}</p>}
    </footer>
  );
}

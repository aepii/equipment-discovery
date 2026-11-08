import { useState } from "react";

/** Logo (web/public/umkc-logo.png, when present), product name and event tag. */
export function Header() {
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
      <span className="mono site-header__event">HACK-A-ROO 2026</span>
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

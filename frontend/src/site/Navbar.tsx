import { useEffect, useState } from "react";

import { navigate, useScrollTo } from "./router";
import { useScrolled } from "./useReveal";

const SECTIONS = [
  { id: "how", label: "How it works" },
  { id: "capture", label: "Capture" },
  { id: "nebraska", label: "The Field" },
] as const;

/** The wordmark: an ember over a horizon line. Drawn, not imported. */
export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg
      className="se-logo"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="se-ember" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--se-ember)" />
          <stop offset="100%" stopColor="var(--se-red-bright)" />
        </linearGradient>
      </defs>
      <circle cx="16" cy="13" r="7" fill="url(#se-ember)" />
      <circle cx="16" cy="13" r="11" fill="none" stroke="var(--se-red)" strokeWidth="1.25" opacity="0.55" />
      <path d="M2 24h28" stroke="var(--se-red-bright)" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M7 28h18" stroke="var(--se-red)" strokeWidth="1.25" strokeLinecap="round" opacity="0.6" />
    </svg>
  );
}

export default function Navbar() {
  const scrolled = useScrolled(20);
  const [open, setOpen] = useState(false);
  const scrollTo = useScrollTo();

  // A drawer that survives a resize into desktop layout would leave the page
  // scroll-locked with no visible way out.
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();

    window.addEventListener("resize", close);
    window.addEventListener("keydown", onKey);
    document.body.classList.add("se-no-scroll");

    return () => {
      window.removeEventListener("resize", close);
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("se-no-scroll");
    };
  }, [open]);

  function go(id: string) {
    setOpen(false);
    scrollTo(id);
  }

  return (
    <header className={`se-nav${scrolled ? " is-scrolled" : ""}`}>
      <div className="se-nav-inner">
        <a
          className="se-brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            setOpen(false);
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
        >
          <Logo />
          <span className="se-brand-name">
            Scorched<span className="se-brand-accent">Earth</span>
          </span>
        </a>

        <nav className="se-nav-links" aria-label="Sections">
          {SECTIONS.map((s) => (
            <button key={s.id} type="button" onClick={() => go(s.id)}>
              {s.label}
            </button>
          ))}
        </nav>

        <div className="se-nav-actions">
          <a
            className="se-btn se-btn-primary se-btn-sm"
            href="/map"
            onClick={(e) => {
              e.preventDefault();
              navigate("map");
            }}
          >
            Launch Map
          </a>

          <button
            type="button"
            className="se-burger"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <span />
            <span />
            <span />
          </button>
        </div>
      </div>

      {open && (
        <div className="se-drawer" role="dialog" aria-modal="true" aria-label="Menu">
          {SECTIONS.map((s) => (
            <button key={s.id} type="button" onClick={() => go(s.id)}>
              {s.label}
            </button>
          ))}
          <a
            className="se-btn se-btn-primary"
            href="/map"
            onClick={(e) => {
              e.preventDefault();
              setOpen(false);
              navigate("map");
            }}
          >
            Launch Map
          </a>
        </div>
      )}
    </header>
  );
}

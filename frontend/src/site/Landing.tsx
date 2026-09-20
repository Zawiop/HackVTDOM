import type { ReactNode } from "react";

import Navbar, { Logo } from "./Navbar";
import { navigate, useScrollTo } from "./router";
import { useReveal } from "./useReveal";

/**
 * The landing page.
 *
 * The map is the product; this exists so that arriving at it is a decision
 * rather than an ambush. Visiting the root used to drop a first-time visitor
 * straight into a 3D scene of Blacksburg with eleven panels and no statement
 * of what any of it was for.
 *
 * Everything here is presentational and reads no application state, so it
 * cannot break the map: the two screens share tokens and a router and nothing
 * else.
 */

function Reveal({
  children,
  delay = 0,
  as: Tag = "div",
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  as?: "div" | "section" | "li" | "article";
  className?: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>();
  return (
    <Tag
      ref={ref as never}
      className={`se-reveal${shown ? " is-shown" : ""} ${className}`.trim()}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </Tag>
  );
}

const STEPS = [
  {
    n: "01",
    title: "Name a building",
    body: "Type an address or drop a pin. The real footprint comes back from OpenStreetMap — the actual polygon, its true width and depth, and the buildings standing next to it.",
  },
  {
    n: "02",
    title: "Choose its fate",
    body: "Five world states along a spectrum from present to collapsed — reclaimed, flooded, scorched, buried, petrified — or describe the ruin you want in your own words.",
  },
  {
    n: "03",
    title: "Watch it fall",
    body: "The photograph is redesigned, then reconstructed into geometry. What comes back is a mesh, not a picture: something with mass, sitting in space.",
  },
  {
    n: "04",
    title: "Put it back",
    body: "Rotation is searched against the real footprint, scale fitted to its true dimensions, and the base set on the ground. The ruin stands exactly where the building stood.",
  },
];

const CAPTURE = [
  {
    label: "Take Photo",
    body: "Opens the rear camera straight from the page. Stand in front of the building and shoot.",
  },
  {
    label: "Choose Photo",
    body: "Pulls from the camera roll, for the one you already took on the walk over.",
  },
  {
    label: "Upload File",
    body: "The desktop route, and the way to hand over several angles at once.",
  },
];

export default function Landing() {
  const scrollTo = useScrollTo();

  return (
    <div className="se-site">
      <Navbar />

      {/* --- hero ------------------------------------------------------ */}
      <section className="se-hero" id="top">
        <div className="se-hero-bg" aria-hidden="true">
          <span className="se-glow se-glow-a" />
          <span className="se-glow se-glow-b" />
          <span className="se-horizon" />
          <span className="se-embers">
            {Array.from({ length: 14 }, (_, i) => (
              <i key={i} style={{ "--i": i } as React.CSSProperties} />
            ))}
          </span>
        </div>

        <div className="se-hero-inner">
          <p className="se-eyebrow se-fade" style={{ animationDelay: "80ms" }}>
            <span className="se-dot" /> Field instrument · Scorched Nebraska
          </p>

          <h1 className="se-hero-title">
            <span className="se-fade" style={{ animationDelay: "160ms" }}>
              Scorched
            </span>{" "}
            <span className="se-fade se-hero-title-accent" style={{ animationDelay: "260ms" }}>
              Earth
            </span>
          </h1>

          <p className="se-hero-lede se-fade" style={{ animationDelay: "380ms" }}>
            Take a photograph of a real building. Choose how the world ends for it.
            Watch the ruin rise on the map at the exact coordinates, footprint and
            scale of the thing that used to stand there.
          </p>

          <div className="se-hero-cta se-fade" style={{ animationDelay: "480ms" }}>
            <a
              className="se-btn se-btn-primary se-btn-lg"
              href="/map"
              onClick={(e) => {
                e.preventDefault();
                navigate("map");
              }}
            >
              Launch Map
              <ArrowIcon />
            </a>
            <button
              type="button"
              className="se-btn se-btn-ghost se-btn-lg"
              onClick={() => scrollTo("how")}
            >
              How it works
            </button>
          </div>

          <dl className="se-stats se-fade" style={{ animationDelay: "600ms" }}>
            <div>
              <dt>Real footprints</dt>
              <dd>OpenStreetMap</dd>
            </div>
            <div>
              <dt>World states</dt>
              <dd>Five, or your own</dd>
            </div>
            <div>
              <dt>Placement</dt>
              <dd>Rotation · scale · ground</dd>
            </div>
          </dl>
        </div>

        <button
          type="button"
          className="se-scroll-cue"
          onClick={() => scrollTo("how")}
          aria-label="Scroll to how it works"
        >
          <span />
        </button>
      </section>

      {/* --- how it works ---------------------------------------------- */}
      <section className="se-section" id="how">
        <div className="se-wrap">
          <Reveal>
            <p className="se-eyebrow">The pipeline</p>
            <h2 className="se-h2">
              From a photograph to a ruin that <em>holds its ground</em>
            </h2>
            <p className="se-section-lede">
              Every step is anchored to something real. Nothing here is decoration on
              top of a map — the geometry is fitted to the building that is actually
              there.
            </p>
          </Reveal>

          <ol className="se-steps">
            {STEPS.map((step, i) => (
              <Reveal as="li" key={step.n} delay={i * 90} className="se-step">
                <span className="se-step-n">{step.n}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* --- capture ---------------------------------------------------- */}
      <section className="se-section se-section-alt" id="capture">
        <div className="se-wrap se-split">
          <Reveal className="se-split-copy">
            <p className="se-eyebrow">Built for the walk</p>
            <h2 className="se-h2">
              Shoot it where you <em>stand</em>
            </h2>
            <p className="se-section-lede">
              The best photograph of a building is the one taken in front of it. On a
              phone the camera opens straight from the page — no app, no account, no
              transferring files off a device to get started.
            </p>

            <ul className="se-capture">
              {CAPTURE.map((c) => (
                <li key={c.label}>
                  <strong>{c.label}</strong>
                  <span>{c.body}</span>
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal className="se-split-visual" delay={120}>
            <div className="se-phone" aria-hidden="true">
              <div className="se-phone-screen">
                <div className="se-phone-bar">
                  <Logo size={14} />
                  <span>Scorched Earth</span>
                </div>
                <p className="se-phone-label">photo of the building (required)</p>
                <div className="se-phone-actions">
                  <span className="se-phone-btn is-primary">Take Photo</span>
                  <span className="se-phone-btn">Choose Photo</span>
                  <span className="se-phone-btn">Upload File</span>
                </div>
                <p className="se-phone-label">world state</p>
                <div className="se-phone-chips">
                  {["reclaimed", "flooded", "scorched", "buried", "petrified"].map((w, i) => (
                    <span key={w} className={i === 2 ? "is-active" : ""}>
                      {w}
                    </span>
                  ))}
                </div>
                <span className="se-phone-cta">generate</span>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* --- the Scorched Nebraska connection --------------------------- */}
      <section className="se-section" id="nebraska">
        <div className="se-wrap">
          <Reveal className="se-neb">
            <p className="se-eyebrow">Companion instrument</p>
            <h2 className="se-h2">
              A field tool for <em>Scorched Nebraska</em>
            </h2>

            <div className="se-neb-body">
              <p>
                Scorched Nebraska keeps its field notes, overlays and operational
                fiction at the far end of a long road. Scorched Earth is the
                instrument you carry down it — a way to take the world you already
                know and see it after.
              </p>
              <p>
                Point it at a lecture hall, a corner shop, the house you grew up in.
                The same five states the fiction runs on are the states you apply,
                written once and held server-side so every ruin reads as though it
                came out of the same long weather. What you make persists on a
                shared map, and the next person to arrive finds your buildings
                already standing.
              </p>
              <a
                className="se-btn se-btn-ghost"
                href="https://www.scorchednebraska.com/"
                target="_blank"
                rel="noopener noreferrer"
              >
                Visit Scorched Nebraska
                <ExternalIcon />
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      {/* --- closing CTA ------------------------------------------------ */}
      <section className="se-cta-band">
        <div className="se-wrap">
          <Reveal>
            <h2 className="se-h2 se-cta-title">Pick a building. End its world.</h2>
            <p className="se-section-lede">
              No account, nothing to install. The map is one tap away.
            </p>
            <a
              className="se-btn se-btn-primary se-btn-lg"
              href="/map"
              onClick={(e) => {
                e.preventDefault();
                navigate("map");
              }}
            >
              Start Exploring
              <ArrowIcon />
            </a>
          </Reveal>
        </div>
      </section>

      <footer className="se-footer">
        <div className="se-wrap se-footer-inner">
          <div className="se-footer-brand">
            <Logo size={20} />
            <span>Scorched Earth</span>
          </div>
          <p className="se-footer-credit">
            Map data © OpenStreetMap contributors (ODbL) · Street-level imagery ©
            Mapillary contributors
          </p>
          <a
            className="se-footer-link"
            href="/map"
            onClick={(e) => {
              e.preventDefault();
              navigate("map");
            }}
          >
            Launch Map →
          </a>
        </div>
      </footer>
    </div>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="se-btn-icon">
      <path d="M5 12h13M12 5l7 7-7 7" />
    </svg>
  );
}

function ExternalIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="se-btn-icon">
      <path d="M14 4h6v6" />
      <path d="M20 4l-9 9" />
      <path d="M18 14v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h5" />
    </svg>
  );
}

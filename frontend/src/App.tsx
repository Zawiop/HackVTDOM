import { useRef, useState } from "react";
import { geocode, getFootprint } from "./api/client";
import type { FootprintCandidate, FootprintResult, GeocodeResult } from "./types/contract";

type Status = "idle" | "geocoding" | "footprinting" | "done" | "error";

export default function App() {
  const [query, setQuery] = useState("Torgersen Hall, Blacksburg, VA");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [place, setPlace] = useState<GeocodeResult | null>(null);
  const [footprint, setFootprint] = useState<FootprintResult | null>(null);
  const [chosen, setChosen] = useState<FootprintCandidate | null>(null);
  const inflight = useRef<AbortController | null>(null);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;

    setError(null);
    setPlace(null);
    setFootprint(null);
    setChosen(null);

    try {
      setStatus("geocoding");
      const found = await geocode(query, controller.signal);
      setPlace(found);
      if (!found.found || found.lat === null || found.lng === null) {
        setStatus("done");
        return;
      }

      setStatus("footprinting");
      const result = await getFootprint(found.lat, found.lng, controller.signal);
      setFootprint(result);
      setChosen(result.selected);
      setStatus("done");
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }

  const busy = status === "geocoding" || status === "footprinting";
  const active = chosen ?? footprint?.selected ?? null;

  return (
    <main className="app">
      <header>
        <h1>Scorched Nebraska</h1>
        <p className="sub">Entry pipeline — address to real building footprint.</p>
      </header>

      <form onSubmit={run}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter a building address"
          aria-label="Building address"
        />
        <button type="submit" disabled={busy || !query.trim()}>
          {busy ? "Working…" : "Locate"}
        </button>
      </form>

      {status === "geocoding" && <p className="note">Geocoding address…</p>}
      {status === "footprinting" && <p className="note">Finding the building footprint…</p>}
      {error && <p className="note error">{error}</p>}

      {place && !place.found && (
        <p className="note error">
          Address not found. Try a different wording, or click the map once step 12 lands.
        </p>
      )}

      {place?.found && (
        <section className="card">
          <h2>Located</h2>
          <p>{place.address}</p>
          <p className="mono">
            {place.lat?.toFixed(6)}, {place.lng?.toFixed(6)}
          </p>
        </section>
      )}

      {footprint && (
        <section className="card">
          <h2>
            Footprint{" "}
            <span className={`badge ${footprint.confidence}`}>{footprint.confidence}</span>
          </h2>
          <p className="note">{footprint.reason}</p>

          {footprint.candidates.length > 1 && (
            <>
              <p className="note">
                {footprint.confidence === "auto-low"
                  ? "Ambiguous match — pick the right building (step 09 will do this on the map):"
                  : "Other buildings within the match radius:"}
              </p>
              <ul className="candidates">
                {footprint.candidates.map((candidate) => (
                  <li key={`${candidate.osmType}-${candidate.osmId}`}>
                    <button
                      type="button"
                      className={active?.osmId === candidate.osmId ? "chosen" : ""}
                      onClick={() => setChosen(candidate)}
                    >
                      {candidate.tags.name ?? `${candidate.osmType} ${candidate.osmId}`} —{" "}
                      {candidate.distanceMeters.toFixed(1)} m away
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {active ? (
            <dl className="facts">
              <dt>Building</dt>
              <dd>{active.tags.name ?? "(unnamed)"}</dd>
              <dt>OSM</dt>
              <dd className="mono">
                {active.osmType} {active.osmId}
              </dd>
              <dt>Width × depth</dt>
              <dd className="mono">
                {active.footprintWidthMeters} × {active.footprintDepthMeters} m
              </dd>
              <dt>Rotation guess</dt>
              <dd className="mono">{active.rotationDegrees}°</dd>
              <dt>Polygon</dt>
              <dd className="mono">{active.geometry.length} points</dd>
            </dl>
          ) : (
            <p className="note">No footprint selected — this routes to manual review.</p>
          )}

          <p className="note">
            {footprint.neighbors.length} neighbours cached for collision + propagate ·{" "}
            {footprint.cached ? "served from cache" : `live from ${new URL(footprint.source).host}`}
          </p>
        </section>
      )}

      <footer>© OpenStreetMap contributors</footer>
    </main>
  );
}

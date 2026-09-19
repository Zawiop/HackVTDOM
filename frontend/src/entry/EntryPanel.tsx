import { useRef, useState } from "react";
import { geocode, getFootprint } from "../api/client";
import type { FootprintCandidate, FootprintResult, GeocodeResult } from "../types/contract";

type Status = "idle" | "geocoding" | "footprinting" | "done" | "error";

interface Props {
  /** Fires once a building footprint is resolved, so the map can fly to it. */
  onLocated?: (lat: number, lng: number, footprint: FootprintResult) => void;
}

/** Steps 01-02: address in, real building footprint out. */
export default function EntryPanel({ onLocated }: Props) {
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
      onLocated?.(found.lat, found.lng, result);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }

  const busy = status === "geocoding" || status === "footprinting";
  const active = chosen ?? footprint?.selected ?? null;

  return (
    <>
      <h3>locate a building</h3>

      <form className="entry-form" onSubmit={run}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter a building address"
          aria-label="Building address"
        />
        <button type="submit" disabled={busy || !query.trim()}>
          {busy ? "…" : "locate"}
        </button>
      </form>

      {status === "geocoding" && <p className="hint">Geocoding address…</p>}
      {status === "footprinting" && <p className="hint">Finding the building footprint…</p>}
      {error && <p className="hint entry-error">{error}</p>}

      {place && !place.found && (
        <p className="hint entry-error">Address not found — try a different wording.</p>
      )}

      {footprint && (
        <>
          <p className="hint">
            <span className={`entry-badge ${footprint.confidence}`}>{footprint.confidence}</span>{" "}
            {footprint.reason}
          </p>

          {footprint.candidates.length > 1 && (
            <div className="btn-grid">
              {footprint.candidates.map((candidate) => (
                <button
                  key={`${candidate.osmType}-${candidate.osmId}`}
                  type="button"
                  className={active?.osmId === candidate.osmId ? "active" : ""}
                  onClick={() => setChosen(candidate)}
                >
                  {candidate.tags.name ?? `${candidate.osmType} ${candidate.osmId}`} ·{" "}
                  {candidate.distanceMeters.toFixed(0)} m
                </button>
              ))}
            </div>
          )}

          {active ? (
            <p className="mono-sm">
              {active.tags.name ?? "(unnamed)"}
              <br />
              {active.footprintWidthMeters} × {active.footprintDepthMeters} m · {active.rotationDegrees}°
              <br />
              {footprint.neighbors.length} neighbours cached
              {footprint.cached ? " · from cache" : ""}
            </p>
          ) : (
            <p className="hint">Ambiguous — pick the right building above.</p>
          )}
        </>
      )}
    </>
  );
}

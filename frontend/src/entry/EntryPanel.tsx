import { useEffect, useRef, useState } from "react";
import { geocode, getFootprint } from "../api/client";
import type {
  FootprintCandidate,
  FootprintResult,
  GeocodeResult,
} from "../types/contract";

type Status = "idle" | "geocoding" | "footprinting" | "done" | "error";

export interface LocatedPlace {
  lat: number;
  lng: number;
  address: string | null;
  footprint: FootprintResult | null;
  selected: FootprintCandidate | null;
}

/**
 * Steps 01-02 entry pipeline: address → coordinate → real building footprint.
 *
 * Also handles the map-click path, which skips geocoding entirely because a
 * click already gives a coordinate. `clickedPoint` changing runs the footprint
 * lookup for that point.
 */
export default function EntryPanel({
  clickedPoint,
  onLocated,
}: {
  clickedPoint?: { lat: number; lng: number } | null;
  onLocated?: (place: LocatedPlace) => void;
}) {
  const [query, setQuery] = useState("Burruss Hall, Blacksburg, VA");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [place, setPlace] = useState<GeocodeResult | null>(null);
  const [footprint, setFootprint] = useState<FootprintResult | null>(null);
  const [chosen, setChosen] = useState<FootprintCandidate | null>(null);
  const inflight = useRef<AbortController | null>(null);

  async function lookupFootprint(
    lat: number,
    lng: number,
    address: string | null,
    controller: AbortController,
  ) {
    setStatus("footprinting");
    const result = await getFootprint(lat, lng, controller.signal);
    setFootprint(result);
    setChosen(result.selected);
    setStatus("done");
    onLocated?.({ lat, lng, address, footprint: result, selected: result.selected });
  }

  function beginRequest() {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setError(null);
    setPlace(null);
    setFootprint(null);
    setChosen(null);
    return controller;
  }

  async function run(event: React.FormEvent) {
    event.preventDefault();
    const controller = beginRequest();
    try {
      setStatus("geocoding");
      const found = await geocode(query, controller.signal);
      setPlace(found);
      if (!found.found || found.lat === null || found.lng === null) {
        setStatus("done");
        return;
      }
      await lookupFootprint(found.lat, found.lng, found.address, controller);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }

  // Map-click path: a click already gives a coordinate, so step 01 is skipped.
  useEffect(() => {
    if (!clickedPoint) return;
    const controller = beginRequest();
    const label = `${clickedPoint.lat.toFixed(5)}, ${clickedPoint.lng.toFixed(5)}`;
    setPlace({
      found: true, address: `map click — ${label}`,
      lat: clickedPoint.lat, lng: clickedPoint.lng,
      placeId: null, boundingBox: null, addressDetails: null,
      attribution: "© OpenStreetMap contributors",
    });
    lookupFootprint(clickedPoint.lat, clickedPoint.lng, `map click — ${label}`, controller)
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clickedPoint?.lat, clickedPoint?.lng]);

  const busy = status === "geocoding" || status === "footprinting";
  const active = chosen ?? footprint?.selected ?? null;

  return (
    <>
      <h3>address → footprint</h3>
      <form onSubmit={run} className="entry-form">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter a building address"
          aria-label="Building address"
        />
        <button type="submit" disabled={busy || !query.trim()}>
          {busy ? "…" : "Locate"}
        </button>
      </form>
      <p className="hint">Or click anywhere on the map to skip geocoding.</p>

      {status === "geocoding" && <p className="mono-sm">Geocoding address…</p>}
      {status === "footprinting" && <p className="mono-sm">Finding the footprint…</p>}
      {error && <p className="mono-sm error-text">{error}</p>}

      {place && !place.found && (
        <p className="mono-sm error-text">
          Address not found — try different wording, or click the map.
        </p>
      )}

      {footprint && (
        <>
          <div className="spread push-top">
            <span className="mono-sm">{active?.tags?.name ?? "footprint"}</span>
            <span className={`badge badge--${footprint.confidence}`}>
              {footprint.confidence}
            </span>
          </div>
          <p className="hint">{footprint.reason}</p>

          {footprint.candidates.length > 1 && (
            <ul className="timeline compact">
              {footprint.candidates.map((candidate) => (
                <li
                  key={`${candidate.osmType}-${candidate.osmId}`}
                  className={active?.osmId === candidate.osmId ? "current" : ""}
                  onClick={() => setChosen(candidate)}
                >
                  <span>{candidate.tags?.name ?? `${candidate.osmType} ${candidate.osmId}`}</span>
                  <span className="mono-sm">{candidate.distanceMeters.toFixed(0)}m</span>
                </li>
              ))}
            </ul>
          )}

          {active && (
            <div className="mono-sm">
              {active.footprintWidthMeters} × {active.footprintDepthMeters} m ·{" "}
              {active.rotationDegrees}° · {active.geometry.length} pts
            </div>
          )}
          <div className="mono-sm">
            {footprint.neighbors.length} neighbours cached for propagate
          </div>
        </>
      )}
    </>
  );
}

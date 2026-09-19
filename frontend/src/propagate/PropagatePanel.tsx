import { useState } from "react";
import { propagate as propagateApi } from "../api/client";
import type {
  FootprintCandidate,
  Generation,
  PropagateResponse,
} from "../types/contract";
import type { PropagateState } from "../map/MapView";

/**
 * Step 10: spread one building's World State across its neighbours.
 *
 * This reveals rows that were pre-baked before judging — it never kicks off
 * generation live, which is exactly what 10-propagate.md warns against. If a
 * neighbour inside the radius has no pre-baked row it comes back as pending,
 * so the count stays honest instead of quietly showing fewer buildings.
 */
const RADII = [50, 100, 250] as const;
type Radius = (typeof RADII)[number];

export default function PropagatePanel({
  source,
  neighbors,
  onResult,
  onClear,
}: {
  source: Generation;
  /** Step 02's cached neighbours, passed straight through — never re-fetched. */
  neighbors?: FootprintCandidate[];
  onResult?: (state: PropagateState) => void;
  onClear?: () => void;
}) {
  const [radius, setRadius] = useState<Radius>(100);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PropagateResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function run(r: Radius) {
    setRadius(r);
    setBusy(true);
    setError(null);
    try {
      const res = await propagateApi(source.id, r, neighbors ?? []);
      setResult(res);
      onResult?.({
        active: true,
        source,
        radiusMeters: r,
        revealed: res.revealed,
        pending: res.pending,
      });
    } catch (e) {
      console.error("[propagate] failed", e);
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }

  function clear() {
    setResult(null);
    setError(null);
    onClear?.();
  }

  return (
    <>
      <h3>world propagate</h3>
      <div className="mono-sm push-bottom">
        spread “{source.world_state ?? "—"}” from {(source.address ?? "").split(",")[0]}
      </div>
      <div className="btn-grid btn-grid-3">
        {RADII.map((r) => (
          <button
            key={r}
            className={result && radius === r ? "active" : ""}
            disabled={busy}
            onClick={() => run(r)}
          >
            {r}m
          </button>
        ))}
      </div>

      {error && <div className="mono-sm error-text push-top">propagate failed — {error.message}</div>}

      {result && (
        <div className="push-top">
          <div className="mono-sm">
            {result.counts.revealed} revealed
            {result.counts.pending > 0 && <> · {result.counts.pending} not pre-baked</>}
          </div>
          <ul className="timeline compact">
            {result.revealed.map((g) => (
              <li key={g.id} className="static">
                <span>{(g.address ?? "").split(",")[0]}</span>
                <span className={`badge ${g.confidence_state}`}>
                  {g.confidence_state}
                </span>
              </li>
            ))}
          </ul>
          <button onClick={clear}>clear</button>
        </div>
      )}
    </>
  );
}

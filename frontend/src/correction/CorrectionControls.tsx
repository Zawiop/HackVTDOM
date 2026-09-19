import { useEffect, useState } from "react";
import { correctGeneration } from "../api/client";
import { offsetMeters } from "../lib/geo";
import type {
  Generation,
  PlacementOverrides,
  PlacementRecord,
} from "../types/contract";

/**
 * Step 09: manual correction for a flagged placement.
 *
 * Deliberately buttons/slider/arrow-keys rather than freeform 3D dragging —
 * 09-correction-ui.md calls dragging out by name as a time sink. Every control
 * binds to a transform field that already exists, so nothing is recomputed.
 *
 * Edits preview live on the map via `onPreview`; only Save writes to the
 * backend, which flips the row to `manually-verified`.
 */
const NUDGE_M = 0.5;
const NUDGE_SHIFT_M = 5;

type Position = PlacementRecord["position"];

export default function CorrectionControls({
  row,
  onPreview,
  onSaved,
}: {
  row: Generation;
  onPreview?: (o: PlacementOverrides | null) => void;
  onSaved?: (updated: Generation) => void;
}) {
  const savedRotation = row.placement?.rotationDegrees ?? 0;
  const savedScale = row.placement?.scale ?? 1;
  const savedPosition: Position =
    row.placement?.position ?? [row.lat, row.lng, 0];

  const [rotation, setRotation] = useState(savedRotation);
  const [scale, setScale] = useState(savedScale);
  const [position, setPosition] = useState<Position>(savedPosition);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Reset when a different building is selected.
  useEffect(() => {
    setRotation(savedRotation);
    setScale(savedScale);
    setPosition(savedPosition);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.id]);

  // Preview live, without touching the database.
  useEffect(() => {
    onPreview?.({ rotationDegrees: rotation, scale, position });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rotation, scale, position]);

  const candidates = row.placement?.scoredRotationCandidates ?? [];
  const dirty =
    rotation !== savedRotation ||
    scale !== savedScale ||
    JSON.stringify(position) !== JSON.stringify(savedPosition);

  function nudge(e: React.KeyboardEvent<HTMLDivElement>) {
    const step = e.shiftKey ? NUDGE_SHIFT_M : NUDGE_M;
    const moves: Record<string, [number, number]> = {
      ArrowUp: [step, 0],
      ArrowDown: [-step, 0],
      ArrowRight: [0, step],
      ArrowLeft: [0, -step],
    };
    const move = moves[e.key];
    if (!move) return;
    e.preventDefault(); // don't let the map pan underneath us
    const [lat, lng] = offsetMeters(position[0], position[1], move[0], move[1]);
    setPosition([lat, lng, position[2] ?? 0]);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await correctGeneration(row.id, {
        rotationDegrees: rotation,
        scale,
        position,
      });
      onSaved?.(updated);
      onPreview?.(null);
    } catch (e) {
      console.error("[correction] save failed", e);
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSaving(false);
    }
  }

  function reset() {
    setRotation(savedRotation);
    setScale(savedScale);
    setPosition(savedPosition);
    onPreview?.(null);
  }

  return (
    <div tabIndex={0} onKeyDown={nudge} className="correction">
      <h3>rotation — scored candidates</h3>
      {candidates.length ? (
        <div className="btn-grid">
          {candidates.map((c) => (
            <button
              key={c.rotationDegrees}
              className={Math.abs(c.rotationDegrees - rotation) < 0.01 ? "active" : ""}
              onClick={() => setRotation(c.rotationDegrees)}
              title={`IoU ${c.iou}`}
            >
              {Math.round(c.rotationDegrees)}° · {Number(c.iou).toFixed(2)}
            </button>
          ))}
        </div>
      ) : (
        <div className="mono-sm">no scored candidates on this row</div>
      )}
      <div className="row">
        <label>fine</label>
        <input
          type="range" min="0" max="359" step="1"
          value={rotation}
          onChange={(e) => setRotation(Number(e.target.value))}
        />
        <span className="mono-sm">{Math.round(rotation)}°</span>
      </div>

      <h3>scale</h3>
      <div className="row">
        <label>uniform</label>
        <input
          type="range" min="0.2" max="4" step="0.01"
          value={scale}
          onChange={(e) => setScale(Number(e.target.value))}
        />
        <span className="mono-sm">{Number(scale).toFixed(2)}×</span>
      </div>

      <h3>position</h3>
      <p className="hint">
        Click here, then arrow keys to nudge {NUDGE_M}m — hold shift for{" "}
        {NUDGE_SHIFT_M}m.
      </p>
      <div className="mono-sm">
        {Number(position[0]).toFixed(6)}, {Number(position[1]).toFixed(6)}
      </div>

      {error && <div className="mono-sm error-text">save failed — {error.message}</div>}

      <div className="spread push-top">
        <button onClick={reset} disabled={!dirty || saving}>reset</button>
        <button className="primary" onClick={save} disabled={!dirty || saving}>
          {saving ? "saving…" : "save → manually-verified"}
        </button>
      </div>
    </div>
  );
}

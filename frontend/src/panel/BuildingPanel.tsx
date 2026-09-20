import { useEffect, useState } from "react";
import ConfidenceBadge from "./ConfidenceBadge";
import { deleteAddress, deleteGeneration, getHistory } from "../api/client";
import HistoryTimeline from "./HistoryTimeline";
import CorrectionControls from "../correction/CorrectionControls";
import type { Generation, PlacementOverrides, PlacementRecord } from "../types/contract";

/** An image that degrades to a labelled placeholder instead of a broken icon. */
function Thumb({ src, caption }: { src?: string | null; caption: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const missing = !src || failed;
  return (
    <figure>
      {missing ? (
        <div className="thumb-missing">no image</div>
      ) : (
        <img src={src} alt={caption} onError={() => setFailed(true)} />
      )}
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/**
 * Step 12's click panel: source photo beside the generated artifact, the
 * placement readout, the step 11 history timeline, and — for anything the
 * algorithm flagged — the step 09 correction controls inline.
 *
 * A flagged row opens straight into the controls that fix it, rather than
 * showing a warning with no action attached.
 */
export default function BuildingPanel({
  row,
  onClose,
  onPreview,
  onSaved,
  onPickHistory,
  satellite,
  onToggleSatellite,
  isPinned,
  onTogglePin,
  onRemoved,
  onCorrectionToggle,
  draggedPosition,
}: {
  row: Generation;
  onClose: () => void;
  onPreview: (o: PlacementOverrides | null) => void;
  onSaved: (updated: Generation) => void;
  onPickHistory: (row: Generation) => void;
  satellite: boolean;
  onToggleSatellite: () => void;
  isPinned?: (row: Generation) => boolean;
  onTogglePin?: (row: Generation) => void;
  /** Called after rows are removed so the map can drop them. */
  onRemoved?: () => void;
  /** Tells the map whether dragging should move the building or pan. */
  onCorrectionToggle?: (open: boolean) => void;
  draggedPosition?: PlacementRecord["position"] | null;
}) {
  const [history, setHistory] = useState<Generation[] | null>(null);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  // Two-step rather than a browser confirm(): removal cannot be undone, and a
  // stray click on a demo machine should not quietly wipe a building.
  const [confirming, setConfirming] = useState<"state" | "building" | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<Error | null>(null);

  async function remove(scope: "state" | "building") {
    setRemoving(true);
    setRemoveError(null);
    try {
      if (scope === "state") await deleteGeneration(row.id);
      else await deleteAddress(row.address);
      setConfirming(null);
      onRemoved?.();
      onClose();
    } catch (e) {
      console.error("[panel] remove failed", e);
      setRemoveError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setRemoving(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setHistory(null);
    setHistoryError(null);
    getHistory(row.address, controller.signal)
      .then(setHistory)
      .catch((e) => {
        if (controller.signal.aborted) return;
        console.error("[panel] history failed", e);
        setHistoryError(e instanceof Error ? e : new Error(String(e)));
      });
    return () => controller.abort();
  }, [row.address, row.confidence_state, row.id]);

  // A flagged building opens with its fix already expanded.
  useEffect(() => {
    setShowCorrection(row.confidence_state === "auto-low");
    setConfirming(null);
    setRemoveError(null);
  }, [row.id, row.confidence_state]);

  // Dragging only moves a building while its correction controls are open;
  // the rest of the time a drag on the map has to pan, as it always did.
  useEffect(() => {
    onCorrectionToggle?.(showCorrection);
    return () => onCorrectionToggle?.(false);
  }, [showCorrection, onCorrectionToggle]);

  const p = row.placement ?? {};
  const bestIou = (p.scoredRotationCandidates ?? [])
    .map((c) => Number(c.iou))
    .reduce((a, b) => Math.max(a, b), 0);

  return (
    <aside className="panel panel-right">
      <div className="spread">
        <h2>{(row.address ?? "").split(",")[0]}</h2>
        <button onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className="spread push-bottom">
        <span className="mono-sm">{row.world_state ?? "no world state"}</span>
        <ConfidenceBadge state={row.confidence_state} />
      </div>

      <div className="thumbs">
        <Thumb src={row.source_photo} caption="source photo" />
        <Thumb src={row.artifact} caption={`artifact — ${row.world_state ?? "—"}`} />
      </div>

      <h3>imagery</h3>
      <div className="spread">
        <button className={satellite ? "active" : ""} onClick={onToggleSatellite}>
          {satellite ? "satellite ✓" : "satellite"}
        </button>
        <span className="mono-sm">
          {Number(row.lat).toFixed(5)}, {Number(row.lng).toFixed(5)}
        </span>
      </div>

      <h3>placement</h3>
      <div className="mono-sm">
        rotation {Math.round(p.rotationDegrees ?? 0)}° · scale{" "}
        {Number(p.scale ?? 1).toFixed(2)}× · z{" "}
        {Number(p.position?.[2] ?? 0).toFixed(2)}m
        {bestIou > 0 && <> · best IoU {bestIou.toFixed(2)}</>}
      </div>
      <div className="mono-sm">mesh: {row.mesh_url ?? "—"}</div>

      <div className="spread push-top">
        <h3 className="inline-h3">correction</h3>
        <button onClick={() => setShowCorrection((v) => !v)}>
          {showCorrection ? "hide" : "adjust"}
        </button>
      </div>
      {showCorrection && (
        <CorrectionControls
          row={row}
          onPreview={onPreview}
          onSaved={onSaved}
          draggedPosition={draggedPosition}
        />
      )}

      <h3>history — this address</h3>
      {historyError ? (
        <div className="mono-sm error-text">history failed — {historyError.message}</div>
      ) : (
        <HistoryTimeline
          history={history}
          currentId={row.id}
          onPick={onPickHistory}
          isPinned={isPinned}
          onTogglePin={onTogglePin}
        />
      )}

      <h3>remove</h3>
      {removeError && (
        <div className="mono-sm error-text">remove failed — {removeError.message}</div>
      )}
      {confirming ? (
        <>
          <p className="hint">
            {confirming === "state"
              ? (history?.length ?? 1) < 2
                ? `Remove the ${row.world_state ?? "current"} state? It is the only one, so the building goes with it.`
                : `Remove the ${row.world_state ?? "current"} state of this building? Its other ${(history?.length ?? 2) - 1} stay.`
              : `Remove ${(row.address ?? "").split(",")[0]} and all ${history?.length ?? 1} of its states?`}{" "}
            This cannot be undone.
          </p>
          <div className="btn-grid">
            <button onClick={() => setConfirming(null)} disabled={removing}>cancel</button>
            <button className="danger" onClick={() => remove(confirming)} disabled={removing}>
              {removing ? "removing…" : "yes, remove"}
            </button>
          </div>
        </>
      ) : (
        <div className="btn-grid">
          <button onClick={() => setConfirming("state")}>this state</button>
          <button onClick={() => setConfirming("building")}>whole building</button>
        </div>
      )}
      <p className="hint">
        {(history?.length ?? 1) < 2
          ? "Only one state here, so removing it clears the building and its terrain."
          : "Removing a state leaves the building's other states in place."}
      </p>
    </aside>
  );
}

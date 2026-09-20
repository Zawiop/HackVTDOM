import { useEffect, useRef, useState } from "react";
import { ApiError, generateImage, getWorldStates } from "../api/client";
import type { SideView } from "../api/client";
import MapillarySuggestions from "../photo/MapillarySuggestions";
import { spectrumIndex, swatchFor } from "./palette";
import type {
  GenerateImageResult,
  WorldState,
  WorldStateOption,
} from "../types/contract";

interface Props {
  /** The building step 01/02 resolved. Null until something is located. */
  address: string | null;
  /** Its coordinate, for step 03's optional street-level imagery lookup. */
  lat?: number | null;
  lng?: number | null;
  /** The image result, plus any photos the user labelled as other sides of the
   *  building — those drive multi-view reconstruction in the mesh step. */
  onGenerated?: (
    result: GenerateImageResult,
    sideViews?: Partial<Record<SideView, File>>,
  ) => void;
}

/**
 * Step 04 — the World State spectrum, plus step 03's mandatory photo upload and
 * the step 05 call they feed.
 *
 * Framed as Present ↔ Collapsed rather than a filter picker: the five buttons
 * are world-building, not image effects. The picker only ever sends an id — the
 * locked descriptions live on the server so every building gets the same
 * treatment. The freeform field is the one place a user describes their own
 * change, and it *replaces* the preset for that single generation.
 */
type ViewSlot = "front" | SideView | "ignore";

const SIDE_ORDER: SideView[] = ["back", "left", "right"];

/** First photo is the front; the rest take back, left, right, then are ignored. */
function defaultSlot(index: number): ViewSlot {
  if (index === 0) return "front";
  return SIDE_ORDER[index - 1] ?? "ignore";
}

export default function WorldStatePanel({
  address,
  lat = null,
  lng = null,
  onGenerated,
}: Props) {
  const [options, setOptions] = useState<WorldStateOption[]>([]);
  const [chosen, setChosen] = useState<WorldState | null>(null);
  const [override, setOverride] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  // Which side of the building each extra photo shows. The first photo is the
  // front; the rest default to back/left/right in order and can be changed.
  const [sides, setSides] = useState<Record<number, ViewSlot>>({});

  const slotOf = (i: number): ViewSlot => sides[i] ?? defaultSlot(i);
  const frontIndex = photos.findIndex((_, i) => slotOf(i) === "front");

  /** Assign a slot, keeping front and each side unique across the photos. */
  function assignSlot(index: number, slot: ViewSlot) {
    setSides((prev) => {
      const next: Record<number, ViewSlot> = { ...prev };
      photos.forEach((_, i) => {
        if (next[i] === undefined) next[i] = defaultSlot(i);
      });
      if (slot !== "ignore") {
        // Only one photo can hold a given slot; whoever had it steps aside.
        for (const [k, v] of Object.entries(next)) {
          if (Number(k) !== index && v === slot) next[Number(k)] = "ignore";
        }
      }
      next[index] = slot;
      return next;
    });
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateImageResult | null>(null);
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getWorldStates(controller.signal)
      .then(setOptions)
      .catch((err) => {
        if (!controller.signal.aborted) setError(String(err));
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => inflight.current?.abort(), []);

  const usingOverride = override.trim().length > 0;
  const canGenerate = photos.length > 0 && (chosen !== null || usingOverride) && !busy;

  async function generate() {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setBusy(true);
    setError(null);
    setResult(null);

    try {
      const generated = await generateImage(
        photos,
        {
          worldState: chosen ?? undefined,
          worldStatePrompt: override,
          // Only send it when the user actually named a front; otherwise let
          // the backend score the set and pick the best photograph.
          frontIndex: frontIndex >= 0 ? frontIndex : undefined,
        },
        controller.signal,
      );
      setResult(generated);

      // Everything except the photo the backend chose as the front becomes a
      // side view, so extra uploads improve the geometry rather than idling.
      const usedFront = generated.photoSelection?.chosenIndex ?? 0;
      const views: Partial<Record<SideView, File>> = {};
      photos.forEach((file, i) => {
        if (i === usedFront) return; // whichever photo became the front view
        const slot = slotOf(i);
        if (slot === "front" || slot === "ignore") return;
        if (!views[slot]) views[slot] = file;
      });
      onGenerated?.(generated, Object.keys(views).length ? views : undefined);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  if (!address) {
    return (
      <>
        <h3>world state</h3>
        <p className="hint">Locate a building first, then choose how far it has fallen.</p>
      </>
    );
  }

  return (
    <>
      <h3>world state</h3>
      <p className="ws-spectrum-label">
        <span>present</span>
        <span className="ws-spectrum-rule" aria-hidden="true" />
        <span>collapsed</span>
      </p>

      {/* One per row rather than five across a 292 px panel: at that width the
          labels broke mid-word ("reclaim / ed"), and shrinking the type enough
          to fit "petrified" made the whole control unreadable. Down the page
          each name gets a line of its own, and the swatch shows the colour the
          ground will actually turn. */}
      <div className="ws-spectrum" role="radiogroup" aria-label="World State">
        {[...options]
          .sort((a, b) => spectrumIndex(a.id) - spectrumIndex(b.id))
          .map((option) => {
            const selected = chosen === option.id && !usingOverride;
            const { gradient } = swatchFor(option.id);
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={selected}
                className={`ws-option${selected ? " active" : ""}`}
                onClick={() => setChosen(option.id)}
                disabled={busy}
              >
                <span className="ws-swatch" style={{ background: gradient }} aria-hidden="true" />
                <span className="ws-name">{option.label}</span>
                <span className="ws-blurb">{option.blurb}</span>
              </button>
            );
          })}
      </div>

      <label className="ws-field">
        <span className="hint">or describe it yourself</span>
        <textarea
          value={override}
          onChange={(e) => setOverride(e.target.value)}
          placeholder="Replaces the preset for this one generation"
          rows={2}
          disabled={busy}
        />
      </label>

      <label className="ws-field">
        <span className="hint">photo of the building (required)</span>
        {/* The spec's line is "one or more photographs", so the input accepts many. */}
        <input
          type="file"
          accept="image/*"
          multiple
          disabled={busy}
          onChange={(e) => setPhotos(Array.from(e.target.files ?? []))}
        />
      </label>

      {photos.length > 1 && (
        <>
          <p className="hint">
            The front is the photo that gets redesigned. Label the others and
            the mesh is reconstructed from every angle instead of guessing the
            sides it never saw.
          </p>
          <ul className="side-views">
            {photos.map((file, i) => (
              <li key={`${file.name}-${i}`}>
                <span className="mono-sm side-views-name">{file.name}</span>
                <select
                  value={slotOf(i)}
                  onChange={(e) => assignSlot(i, e.target.value as ViewSlot)}
                >
                  <option value="front">front</option>
                  <option value="back">back</option>
                  <option value="left">left</option>
                  <option value="right">right</option>
                  <option value="ignore">ignore</option>
                </select>
              </li>
            ))}
          </ul>
          <p className="hint">
            {frontIndex >= 0
              ? "Only one photo can hold each slot; picking a slot frees it from whichever photo had it."
              : "No front picked — the sharpest, best-exposed photo will be used."}
          </p>
        </>
      )}

      {/*
        Step 03 path B. Renders nothing at all where there is no coverage, which
        is most addresses — the upload above is the required path either way.
      */}
      <MapillarySuggestions
        lat={lat}
        lng={lng}
        // Adds rather than replaces: several Mapillary frames of the same
        // building are different angles of it, which is exactly what
        // multi-view reconstruction wants. Picking the same one twice
        // removes it again.
        onPick={(file) =>
          setPhotos((prev) =>
            prev.some((f) => f.name === file.name)
              ? prev.filter((f) => f.name !== file.name)
              : [...prev, file],
          )
        }
      />

      <button type="button" className="primary" onClick={generate} disabled={!canGenerate}>
        {busy ? "generating…" : "generate"}
      </button>

      {busy && <p className="hint">Up to a minute on the free tier.</p>}
      {error && (
        <p className="hint entry-error">
          {error} <button type="button" onClick={generate}>retry</button>
        </p>
      )}

      {result && (
        <>
          <div className="ws-result">
            <figure>
              <img src={result.sourcePhotoUrl} alt="Original building" />
              <figcaption className="hint">before</figcaption>
            </figure>
            <figure>
              <img src={result.imageUrl} alt="Redesigned building" />
              <figcaption className="hint">after</figcaption>
            </figure>
          </div>
          {result.photoSelection && result.photoSelection.count > 1 && (
            <p className="hint">
              Front: photo {result.photoSelection.chosenIndex + 1} of{" "}
              {result.photoSelection.count}
              {result.photoSelection.chosenName
                ? ` (${result.photoSelection.chosenName})`
                : ""}
              {result.photoSelection.chosenByUser
                ? " — your choice."
                : " — sharpest of the set."}
            </p>
          )}
          <p className="mono-sm">
            {result.promptSource === "override" ? "your description" : result.worldState} ·{" "}
            {result.provider}
            {result.cached ? " · cached" : ` · ${Math.round(result.elapsedMs / 1000)}s`}
          </p>
        </>
      )}
    </>
  );
}

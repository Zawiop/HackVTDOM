import type { Generation } from "../types/contract";

/**
 * Display controls, pulled out of the workflow panel and floated over the map.
 *
 * They were mixed in with "find a building" and "generate a World State",
 * which made one long column where nothing read as more important than
 * anything else. These are the things you reach for *while* looking at the
 * map, so they belong on the map.
 */
export default function ViewBar({
  reveal,
  onReveal,
  satellite,
  onToggleSatellite,
  labels,
  onToggleLabels,
  tour,
  postcardBusy,
  onPostcard,
  disabled,
}: {
  reveal: number;
  onReveal: (value: number) => void;
  satellite: boolean;
  onToggleSatellite: () => void;
  labels: boolean;
  onToggleLabels: () => void;
  tour: {
    running: boolean;
    index: number;
    total: number;
    current: Generation | null;
    toggle: () => void;
  };
  postcardBusy: boolean;
  onPostcard: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="view-bar">
      <div className="reveal">
        <label htmlFor="reveal-slider">reveal</label>
        <input
          id="reveal-slider"
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={reveal}
          disabled={disabled}
          onChange={(e) => onReveal(Number(e.target.value))}
        />
        <span className="mono-sm reveal-readout">
          {reveal >= 0.999 ? "world state" : reveal <= 0.001 ? "today" : `${Math.round(reveal * 100)}%`}
        </span>
        {/* Two clicks for the two ends: a slider is for the in-between, but
            the demo beat is the flip, and dragging to exactly 0 or 1 is fiddly. */}
        <button
          className="subtle tiny"
          onClick={() => onReveal(reveal > 0.5 ? 0 : 1)}
          disabled={disabled}
          title="Flip between today and the World State"
        >
          flip
        </button>
      </div>

      <div className="view-bar-buttons">
        <button className={satellite ? "active" : ""} onClick={onToggleSatellite}>
          satellite
        </button>
        <button className={labels ? "active" : ""} onClick={onToggleLabels}>
          labels
        </button>
        <button
          className={tour.running ? "active" : ""}
          onClick={tour.toggle}
          disabled={disabled || tour.total === 0}
          title={tour.total ? `Fly through all ${tour.total} buildings` : "No buildings yet"}
        >
          {tour.running ? `tour ${tour.index + 1}/${tour.total}` : "tour"}
        </button>
        <button onClick={onPostcard} disabled={disabled || postcardBusy}>
          {postcardBusy ? "saving…" : "postcard"}
        </button>
      </div>
    </div>
  );
}

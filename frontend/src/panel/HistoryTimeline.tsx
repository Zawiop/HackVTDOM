import type { Generation } from "../types/contract";
import ConfidenceBadge from "./ConfidenceBadge";

/**
 * Step 11's timeline: one address's rows in order, "Reality → Flooded → …".
 *
 * This only looks like a list, but it is the visible proof of the schema rule —
 * an address accumulates generations instead of being overwritten by the latest.
 */
export default function HistoryTimeline({
  history,
  currentId,
  onPick,
  isPinned,
  onTogglePin,
}: {
  history: Generation[] | null;
  currentId: string;
  onPick?: (row: Generation) => void;
  /** Is this the state left showing on the building when nothing is selected? */
  isPinned?: (row: Generation) => boolean;
  onTogglePin?: (row: Generation) => void;
}) {
  if (!history) return <div className="mono-sm">loading history…</div>;
  if (history.length <= 1) {
    return (
      <div className="mono-sm">
        single generation — apply another World State to start a timeline
      </div>
    );
  }

  return (
    <ol className="timeline">
      <li className="muted timeline-reality">
        <span>reality</span>
        <span className="mono-sm">source photo</span>
      </li>
      {history.map((row, i) => {
        const pinned = isPinned?.(row) ?? false;
        return (
          <li
            key={row.id}
            className={row.id === currentId ? "current" : ""}
            onClick={() => onPick?.(row)}
            title={row.created_at}
          >
            <span>
              {i + 1}. {row.world_state ?? "unknown state"}
            </span>
            <span className="timeline-actions">
              {onTogglePin && (
                <button
                  type="button"
                  className={pinned ? "pin pinned" : "pin"}
                  title={
                    pinned
                      ? "Showing on the map. Click to go back to the newest state."
                      : "Keep this state on the building after you close this panel."
                  }
                  onClick={(e) => {
                    e.stopPropagation(); // the row click selects; this only pins
                    onTogglePin(row);
                  }}
                >
                  {pinned ? "on map" : "keep"}
                </button>
              )}
              <ConfidenceBadge state={row.confidence_state} />
            </span>
          </li>
        );
      })}
    </ol>
  );
}

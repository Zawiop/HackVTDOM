import type { Generation } from "../types/contract";

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
}: {
  history: Generation[] | null;
  currentId: string;
  onPick?: (row: Generation) => void;
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
      {history.map((row, i) => (
        <li
          key={row.id}
          className={row.id === currentId ? "current" : ""}
          onClick={() => onPick?.(row)}
          title={row.created_at}
        >
          <span>
            {i + 1}. {row.world_state ?? "unknown state"}
          </span>
          <span className={`badge ${row.confidence_state}`}>
            {row.confidence_state}
          </span>
        </li>
      ))}
    </ol>
  );
}

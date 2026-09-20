import type { UndoInfo } from "../api/client";

/**
 * "That removed eighteen buildings — put them back?"
 *
 * Floating rather than tucked into the side panel, because the moment it
 * matters is the moment right after a click the user regrets, and they are
 * looking at the map.
 */
export default function UndoBanner({
  info,
  busy,
  error,
  onUndo,
  onDismiss,
}: {
  info: UndoInfo;
  busy: boolean;
  error: Error | null;
  onUndo: () => void;
  onDismiss: () => void;
}) {
  const what = info.label || `${info.count ?? 0} generation(s)`;
  return (
    <div className="undo-banner" role="status">
      <span className="undo-text">
        Removed <strong>{what}</strong>
      </span>
      {error && <span className="mono-sm error-text">undo failed — {error.message}</span>}
      <button className="primary" onClick={onUndo} disabled={busy}>
        {busy ? "restoring…" : "undo"}
      </button>
      <button className="subtle" onClick={onDismiss} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}

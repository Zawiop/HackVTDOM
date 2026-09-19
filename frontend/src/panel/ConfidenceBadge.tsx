import type { ConfidenceState } from "../types/contract";

/**
 * Step 13's confidence language, in one place so every surface agrees.
 *
 * The three states have to read differently at a glance: `manually-verified` is
 * the human-in-the-loop beat, and 09/14 both lean on a judge being able to *see*
 * it happened rather than take it on trust.
 */
const LABELS: Record<ConfidenceState, string> = {
  "auto-high": "auto",
  "auto-low": "needs review",
  "manually-verified": "✓ verified",
};

export default function ConfidenceBadge({ state }: { state: ConfidenceState }) {
  return (
    <span className={`badge ${state}`} title={state}>
      {LABELS[state] ?? state}
    </span>
  );
}

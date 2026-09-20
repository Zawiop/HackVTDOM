import { useMemo, useState } from "react";
import { visibleRows } from "../map/layers";
import type { Generation } from "../types/contract";

/**
 * Every building in the world, as a list.
 *
 * Before this, the only way to reach a building was to find it on the map and
 * click it — a scavenger hunt that got worse as the world filled up, and one
 * that made the flagged-placement workflow almost undemonstrable: you had to
 * spot an orange ring by eye before you could fix anything.
 *
 * Rows are grouped by address, because a building with three World States is
 * one building, not three entries.
 */

export interface RosterEntry {
  address: string;
  /** The state currently on the map for this address. */
  shown: Generation;
  /** Every state this address has, newest first. */
  states: Generation[];
  flagged: boolean;
  verified: boolean;
}

/** Grouped, sorted, and matched against a filter. Exported for tests. */
export function buildRoster(
  rows: Generation[],
  selectedId: string | null,
  pinnedIds: ReadonlySet<string> | null,
  query = "",
): RosterEntry[] {
  // Reuse the map's own answer to "which state is showing", so the list and
  // the map can never disagree about what you are looking at.
  const showing = new Map(
    visibleRows(rows, selectedId, pinnedIds).map((r) => [r.address || r.id, r]),
  );

  const byAddress = new Map<string, Generation[]>();
  for (const row of rows) {
    const key = row.address || row.id;
    const bucket = byAddress.get(key);
    if (bucket) bucket.push(row);
    else byAddress.set(key, [row]);
  }

  const needle = query.trim().toLowerCase();
  const entries: RosterEntry[] = [];
  for (const [address, states] of byAddress) {
    const sorted = [...states].sort((a, b) =>
      (b.created_at ?? "").localeCompare(a.created_at ?? ""),
    );
    const shown = showing.get(address) ?? sorted[0];
    if (needle) {
      const haystack = `${address} ${sorted.map((s) => s.world_state ?? "").join(" ")}`;
      if (!haystack.toLowerCase().includes(needle)) continue;
    }
    entries.push({
      address,
      shown,
      states: sorted,
      // Flagged if *anything* here needs a look, not just the visible state —
      // otherwise a low-confidence row hides behind a good one and never
      // reaches the fix queue.
      flagged: sorted.some((s) => s.confidence_state === "auto-low"),
      verified: sorted.some((s) => s.confidence_state === "manually-verified"),
    });
  }
  return entries.sort((a, b) => shortName(a.address).localeCompare(shortName(b.address)));
}

export function shortName(address: string): string {
  return (address ?? "").split(",")[0].trim() || "unnamed";
}

/** The flagged entry after the current one, wrapping. Null if none are flagged. */
export function nextFlagged(
  entries: RosterEntry[],
  currentId: string | null,
): Generation | null {
  const flagged = entries
    .flatMap((e) => e.states)
    .filter((s) => s.confidence_state === "auto-low");
  if (!flagged.length) return null;
  const at = flagged.findIndex((s) => s.id === currentId);
  return flagged[(at + 1) % flagged.length];
}

export default function BuildingRoster({
  rows,
  selectedId,
  pinnedIds,
  onSelect,
}: {
  rows: Generation[];
  selectedId: string | null;
  pinnedIds: ReadonlySet<string> | null;
  onSelect: (row: Generation) => void;
}) {
  const [query, setQuery] = useState("");
  const entries = useMemo(
    () => buildRoster(rows, selectedId, pinnedIds, query),
    [rows, selectedId, pinnedIds, query],
  );
  const flaggedCount = useMemo(
    () => rows.filter((r) => r.confidence_state === "auto-low").length,
    [rows],
  );
  const target = useMemo(() => nextFlagged(entries, selectedId), [entries, selectedId]);

  if (!rows.length) return null;

  return (
    <section className="roster">
      {/* No heading here: this always renders inside a <Section> that already
          carries the title and the count. */}
      {rows.length > 4 && (
        <input
          className="roster-search"
          type="search"
          value={query}
          placeholder="filter by name or state"
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Filter buildings"
        />
      )}

      <ul className="roster-list">
        {entries.map((entry) => {
          const isOpen = entry.states.some((s) => s.id === selectedId);
          return (
            <li key={entry.address}>
              <button
                className={`roster-item${isOpen ? " active" : ""}`}
                onClick={() => onSelect(entry.shown)}
                title={entry.address}
              >
                <span
                  className={`roster-dot ${
                    entry.flagged ? "flagged" : entry.verified ? "verified" : "ok"
                  }`}
                  aria-hidden="true"
                />
                <span className="roster-name">{shortName(entry.address)}</span>
                <span className="roster-state mono-sm">
                  {entry.shown.world_state ?? "—"}
                </span>
                {entry.states.length > 1 && (
                  <span className="roster-count mono-sm" title={`${entry.states.length} states`}>
                    ×{entry.states.length}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {!entries.length && <p className="hint">Nothing matches “{query}”.</p>}

      {flaggedCount > 0 && target && (
        <button className="full-width subtle" onClick={() => onSelect(target)}>
          next flagged placement ({flaggedCount})
        </button>
      )}
    </section>
  );
}

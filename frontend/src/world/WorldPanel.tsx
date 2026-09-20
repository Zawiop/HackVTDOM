import { useRef, useState } from "react";
import { importWorld, resetWorld, seedWorld, worldExportUrl } from "../api/client";
import type { ImportResult } from "../api/client";

/**
 * Moving a world between machines, and clearing one.
 *
 * The reason export exists: a stored row points at its mesh and images by URL,
 * those files live in `backend/outputs/` — gitignored, ~350 MB — and so the
 * database on its own is eighteen buildings that render nothing. A bundle
 * carries both halves, which is the difference between a demo that works on
 * one laptop and a demo that works at the table you are given.
 *
 * `seed` is the other end of the same problem: a fresh clone has no world at
 * all, and live generation is the flaky path. The seed buildings are committed
 * to the repo, so they need no network, no quota and no GPU time.
 */
export default function WorldPanel({
  count,
  onChanged,
}: {
  count: number;
  /** Called after anything that changed the world, so the map can refetch. */
  onChanged: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState<null | "seed" | "import" | "reset">(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [replaceOnImport, setReplaceOnImport] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function run<T>(kind: "seed" | "import" | "reset", fn: () => Promise<T>) {
    setBusy(kind);
    setError(null);
    setNote(null);
    try {
      const result = await fn();
      await onChanged();
      return result;
    } catch (e) {
      console.error(`[world] ${kind} failed`, e);
      setError(e instanceof Error ? e : new Error(String(e)));
      return null;
    } finally {
      setBusy(null);
    }
  }

  function describe(r: ImportResult): string {
    const bits = [`${r.imported} added`];
    if (r.skipped_already_present) bits.push(`${r.skipped_already_present} already here`);
    if (r.cleared) bits.push(`${r.cleared} cleared`);
    if (r.files_written) bits.push(`${r.files_written} files`);
    return bits.join(" · ");
  }

  async function onSeed() {
    const r = await run("seed", () => seedWorld("merge"));
    if (r) setNote(describe(r));
  }

  async function onPickFile(file: File | undefined) {
    if (!file) return;
    const r = await run("import", () =>
      importWorld(file, replaceOnImport ? "replace" : "merge"),
    );
    if (r) setNote(describe(r));
    // Cleared so re-picking the same file fires a change event again.
    if (fileRef.current) fileRef.current.value = "";
  }

  async function onReset() {
    const r = await run("reset", () => resetWorld());
    setConfirmingReset(false);
    if (r) {
      setNote(
        r.undoable
          ? `${r.removed} removed — undo is available`
          : // Said plainly: the stash is the only thing standing between a
            // stray click and a lost world, and if it failed to write, the
            // user needs to know before they act on it.
            `${r.removed} removed — the undo stash could not be written, so this is final`,
      );
    }
  }

  return (
    <section className="world-panel">
      {/* No heading: this renders inside a <Section> that already has one. */}
      {error && <div className="mono-sm error-text">{error.message}</div>}
      {note && <div className="mono-sm ok-text">{note}</div>}

      {count === 0 ? (
        <>
          <button className="full-width primary" onClick={onSeed} disabled={busy !== null}>
            {busy === "seed" ? "loading…" : "load demo buildings"}
          </button>
          <p className="hint">
            Eight halls off the Drillfield, committed to the repo — no network,
            no GPU time. The fastest way to a world that shows something.
          </p>
        </>
      ) : (
        <div className="btn-grid">
          <a className="btn-link" href={worldExportUrl()} download>
            export
          </a>
          <button onClick={() => fileRef.current?.click()} disabled={busy !== null}>
            {busy === "import" ? "importing…" : "import"}
          </button>
        </div>
      )}

      <input
        ref={fileRef}
        type="file"
        accept=".zip,.json,application/zip,application/json"
        hidden
        onChange={(e) => void onPickFile(e.target.files?.[0])}
      />

      {count > 0 && (
        <>
          <label className="check-row">
            <input
              type="checkbox"
              checked={replaceOnImport}
              onChange={(e) => setReplaceOnImport(e.target.checked)}
            />
            <span>import replaces the world</span>
          </label>
          <p className="hint">
            Export is a zip of the rows plus every mesh and image they use — it
            opens on another machine. Import defaults to merging, and skips
            anything already here.
          </p>

          <div className="btn-grid">
            <button onClick={onSeed} disabled={busy !== null} className="subtle">
              {busy === "seed" ? "loading…" : "+ demo buildings"}
            </button>
            {confirmingReset ? (
              <button onClick={() => setConfirmingReset(false)} disabled={busy !== null}>
                cancel
              </button>
            ) : (
              <button className="danger" onClick={() => setConfirmingReset(true)}>
                reset world
              </button>
            )}
          </div>

          {confirmingReset && (
            <>
              <p className="hint warn-text">
                Remove all {count} generation{count === 1 ? "" : "s"} and their terrain?
              </p>
              <button className="full-width danger" onClick={onReset} disabled={busy !== null}>
                {busy === "reset" ? "clearing…" : "yes, clear the world"}
              </button>
              <p className="hint">This can be undone — the rows are kept until the next removal.</p>
            </>
          )}
        </>
      )}
    </section>
  );
}

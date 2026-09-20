import { useState } from "react";

import { deleteAddress, ApiError } from "../api/client";
import type { MyWorld } from "./useMyWorld";

/**
 * Clear the world you made, without clearing anyone else's.
 *
 * Scoped to this browser's own buildings on purpose. The map is one shared
 * world and there are no accounts, so an unqualified "delete everything"
 * control would let any visitor wipe the table mid-demo. Narrowing it to what
 * you made keeps the useful half of that button and drops the dangerous half.
 *
 * The genuinely global reset still exists in WorldPanel, still behind
 * ADMIN_TOKEN. This does not widen it.
 */
export default function MyWorldControls({
  world,
  onChanged,
}: {
  world: MyWorld;
  onChanged: () => void | Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const count = world.mine.length;
  const addresses = world.mineAddresses;

  if (count === 0) {
    return (
      <p className="hint">
        Buildings you generate are tracked in this browser, so you can clear
        them without touching anyone else's.
      </p>
    );
  }

  async function clearAll() {
    setBusy(true);
    setError(null);

    const removed: string[] = [];
    const failed: string[] = [];

    // One address at a time rather than a world reset: this must never remove
    // a building this browser did not make.
    for (const address of addresses) {
      try {
        await deleteAddress(address);
        removed.push(address);
      } catch (e) {
        failed.push(address);
        // 401 means the deployment has ADMIN_TOKEN set and this build has no
        // matching key — worth saying plainly rather than "something failed".
        if (e instanceof ApiError && e.status === 401) {
          setError("This deployment locks deletion to an admin key.");
          break;
        }
      }
    }

    if (removed.length > 0) {
      world.forget(world.mineIds);
      await onChanged();
    }
    if (failed.length > 0 && !error) {
      setError(`${failed.length} of ${addresses.length} could not be removed.`);
    }

    setBusy(false);
    setConfirming(false);
  }

  return (
    <>
      {error && <div className="mono-sm error-text">{error}</div>}

      {confirming ? (
        <>
          <p className="hint">
            Remove {count} building{count === 1 ? "" : "s"} you made from the
            shared map? Buildings other people made stay. This cannot be undone.
          </p>
          <div className="btn-grid">
            <button onClick={() => setConfirming(false)} disabled={busy}>
              cancel
            </button>
            <button className="danger" onClick={clearAll} disabled={busy}>
              {busy ? "clearing…" : "yes, clear mine"}
            </button>
          </div>
        </>
      ) : (
        <>
          <button className="danger wide" onClick={() => setConfirming(true)}>
            delete my world ({count})
          </button>
          <p className="hint">
            Removes only the {count} building{count === 1 ? "" : "s"} generated in
            this browser.
          </p>
        </>
      )}
    </>
  );
}

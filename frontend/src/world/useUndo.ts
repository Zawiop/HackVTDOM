import { useCallback, useEffect, useState } from "react";
import { ApiError, peekUndo, undoLast } from "../api/client";
import type { UndoInfo } from "../api/client";

/**
 * One level of undo over the destructive routes.
 *
 * This exists because reset-world was used once, in earnest, and took a world
 * that had cost real GPU time with it. The backend stashes every delete; this
 * asks what is in the stash and offers to put it back.
 *
 * `refresh` is called after anything destructive rather than polled, so the
 * offer appears the moment it becomes true and not up to an interval later.
 */
export function useUndo(onRestored?: () => void | Promise<void>) {
  const [info, setInfo] = useState<UndoInfo>({ available: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  /** Dismissed by the user — still restorable, just not being offered. */
  const [hidden, setHidden] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await peekUndo();
      setInfo(next);
      if (next.available) setHidden(false);
    } catch (e) {
      // A peek that fails is not worth a banner: the worst case is that we do
      // not offer an undo that would have worked, and the route still exists.
      console.warn("[undo] peek failed", e);
      setInfo({ available: false });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const undo = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await undoLast();
      setInfo({ available: false });
      await onRestored?.();
      return result;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // Somebody else already took it, or the stash was cleared. Not an
        // error worth shouting about — just stop offering.
        setInfo({ available: false });
        return null;
      }
      console.error("[undo] failed", e);
      setError(e instanceof Error ? e : new Error(String(e)));
      return null;
    } finally {
      setBusy(false);
    }
  }, [onRestored]);

  return {
    info,
    /** True only when there is something to restore and it has not been waved off. */
    offering: info.available && !hidden,
    busy,
    error,
    refresh,
    undo,
    dismiss: useCallback(() => setHidden(true), []),
  };
}

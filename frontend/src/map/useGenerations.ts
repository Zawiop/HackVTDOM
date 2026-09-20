import { useCallback, useEffect, useState } from "react";
import { listGenerations } from "../api/client";
import type { Generation } from "../types/contract";

/**
 * Loads every persisted generation for the map.
 *
 * A load failure surfaces as `error`, never swallowed into an empty map — an
 * empty map and a broken backend must not look identical to the user.
 */
export function useGenerations() {
  const [rows, setRows] = useState<Generation[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listGenerations();
      setRows(Array.isArray(data) ? data : []);
      setError(null);
    } catch (e) {
      console.error("[useGenerations] load failed", e);
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Replace one row in place after a correction, without a full refetch. */
  const replaceRow = useCallback((updated: Generation) => {
    setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
  }, []);

  return { rows, error, loading, refresh, replaceRow };
}

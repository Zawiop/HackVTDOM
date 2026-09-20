import { useCallback, useEffect, useMemo, useState } from "react";

import type { Generation } from "../types/contract";

/**
 * Which buildings *this browser* made.
 *
 * The problem this solves is a consequence of having no accounts, which is
 * deliberate: the map is one shared world, so "delete everything" cannot mean
 * "delete everything anyone ever made" for whoever happens to click it. That
 * is not a feature, it is a griefing button.
 *
 * Recording ids locally as they are created gives ownership without a login.
 * It is an honest, limited claim — localStorage is per-browser, clearing it
 * forgets what you made, and it is not a server-side control — which is why it
 * only ever *narrows* what the destructive controls will touch. The
 * server-side guard on the global reset (ADMIN_TOKEN, see backend
 * app/security.py) is untouched and stays the real boundary.
 */
const STORAGE_KEY = "scorched-earth:my-generations";

/** A generous cap; the list is ids, but unbounded local storage is still rude. */
const MAX_TRACKED = 500;

function readStored(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string" && v.length > 0);
  } catch {
    // Private window, blocked storage, corrupt value — the map works without it.
    return [];
  }
}

function writeStored(ids: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.slice(-MAX_TRACKED)));
  } catch {
    // Nothing to do: ownership is a convenience, not a correctness requirement.
  }
}

export interface MyWorld {
  /** Ids this browser created that still exist on the server. */
  mineIds: string[];
  /** The rows behind those ids, in the order the map has them. */
  mine: Generation[];
  /** Distinct addresses this browser created. */
  mineAddresses: string[];
  isMine: (row: Generation | null | undefined) => boolean;
  /** Record a newly saved generation. */
  claim: (id: string) => void;
  /** Forget ids that no longer exist server-side (deleted elsewhere, reset, etc.). */
  forget: (ids: string[]) => void;
}

export function useMyWorld(rows: Generation[]): MyWorld {
  const [ids, setIds] = useState<string[]>(() => readStored());

  // Another tab making buildings is still this person; keep the two in step.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setIds(readStored());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const claim = useCallback((id: string) => {
    if (!id) return;
    setIds((prev) => {
      if (prev.includes(id)) return prev;
      const next = [...prev, id];
      writeStored(next);
      return next;
    });
  }, []);

  const forget = useCallback((gone: string[]) => {
    if (gone.length === 0) return;
    const drop = new Set(gone);
    setIds((prev) => {
      const next = prev.filter((id) => !drop.has(id));
      if (next.length === prev.length) return prev;
      writeStored(next);
      return next;
    });
  }, []);

  const owned = useMemo(() => new Set(ids), [ids]);

  // Intersect with what the server actually has, so a world reset or a delete
  // from another machine does not leave a phantom count in the UI.
  const mine = useMemo(() => rows.filter((r) => r.id && owned.has(r.id)), [rows, owned]);

  const mineIds = useMemo(() => mine.map((r) => r.id!).filter(Boolean), [mine]);

  const mineAddresses = useMemo(
    () => [...new Set(mine.map((r) => r.address).filter((a): a is string => Boolean(a)))],
    [mine],
  );

  const isMine = useCallback(
    (row: Generation | null | undefined) => Boolean(row?.id && owned.has(row.id)),
    [owned],
  );

  return { mineIds, mine, mineAddresses, isMine, claim, forget };
}

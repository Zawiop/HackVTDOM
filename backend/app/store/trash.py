"""One level of undo for the destructive routes.

Every delete route parks the rows it is about to remove here first, so
`POST /api/world/undo` can put them straight back. There is no regeneration
involved: the rows are restored verbatim, ids and all, and the mesh and image
files they point at were never touched by a delete in the first place.

Only the most recent batch is kept. That is deliberate — undo exists to walk
back the click you just regretted, and a deep stack of half-worlds is a worse
thing to reason about mid-demo than a single clear "put that back".

The stash is a JSON file rather than process memory so it survives the reload
that a `--reload` dev server does on every edit.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..models import Generation

log = logging.getLogger("scorched.trash")

# A world much larger than this is not something one undo button should be
# holding in a JSON file; the export/import bundle is the right tool there.
MAX_STASHED_ROWS = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stash(path: Path, rows: list[Generation], *, action: str, label: str) -> dict | None:
    """Park `rows` as the undoable batch, replacing whatever was there.

    Never raises: a failure to write the safety net must not stop the delete
    the user actually asked for. It returns None in that case, and the caller
    reports `undoable: false` rather than promising an undo that is not there.
    """
    if not rows:
        return None
    if len(rows) > MAX_STASHED_ROWS:
        log.warning("not stashing %d rows for undo — over the %d cap", len(rows), MAX_STASHED_ROWS)
        return None
    entry = {
        "version": 1,
        "action": action,
        "label": label,
        "stashed_at": _now(),
        "count": len(rows),
        "generations": [r.model_dump(mode="json") for r in rows],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write leaves the previous stash intact
        # instead of a truncated file that neither restores nor reports.
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("could not stash %d row(s) for undo: %s", len(rows), e)
        return None
    log.info("stashed %d row(s) for undo (%s: %s)", len(rows), action, label)
    return {k: entry[k] for k in ("action", "label", "stashed_at", "count")}


def peek(path: Path) -> dict | None:
    """What undo would restore, without restoring it. None if nothing is stashed."""
    entry = _read(path)
    if entry is None:
        return None
    return {k: entry.get(k) for k in ("action", "label", "stashed_at", "count")}


def take(path: Path) -> tuple[list[Generation], dict] | None:
    """Pop the stashed batch. None if there is nothing to undo.

    The file is cleared only after the rows parse, so a stash this build can no
    longer read stays on disk to be looked at rather than silently evaporating.
    """
    entry = _read(path)
    if entry is None:
        return None
    try:
        rows = [Generation(**g) for g in entry.get("generations", [])]
    except Exception as e:  # noqa: BLE001 - a bad stash is reported, not swallowed
        log.error("stashed undo batch could not be parsed: %s", e)
        return None
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("restored %d row(s) but could not clear the stash: %s", len(rows), e)
    meta = {k: entry.get(k) for k in ("action", "label", "stashed_at", "count")}
    return rows, meta


def clear(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not clear the undo stash: %s", e)


def _read(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("undo stash at %s is not valid JSON", path)
        return None
    return entry if isinstance(entry, dict) and entry.get("generations") else None

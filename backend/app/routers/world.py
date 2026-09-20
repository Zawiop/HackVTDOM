"""World-level routes: export, import, seed, undo.

These exist because the interesting half of a generation is not in the
database. A row points at a mesh and two images by URL, those files sit in
`backend/outputs/` (gitignored, ~350 MB), and so a world is not actually
portable unless something carries both halves together. `/api/world/export`
is that something.

`/api/world/undo` is the companion safety net: every destructive route parks
what it removed, and this puts the last batch back verbatim — same ids, same
timestamps, no regeneration and no GPU time.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.datastructures import UploadFile

from ..config import get_settings
from ..services import worldio
from ..services.worldio import BundleError
from ..store import GenerationStore, PersistenceError, get_store, trash

log = logging.getLogger("scorched.world")
router = APIRouter(prefix="/api/world", tags=["world"])

MAX_IMPORT_BYTES = worldio.MAX_BUNDLE_BYTES


def get_trash_path() -> Path:
    """Injected so a test can point undo somewhere harmless."""
    return get_settings().resolved_trash_path


def _loud(e: PersistenceError) -> HTTPException:
    log.error("PERSISTENCE FAILURE [%s]: %s", e.operation, e.detail)
    return HTTPException(status_code=502, detail=f"persistence.{e.operation}: {e.detail}")


def _slug_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


@router.get("/export")
def export_world(
    format: str = Query("bundle", pattern="^(bundle|json)$"),
    store: GenerationStore = Depends(get_store),
):
    """The whole world as a portable file.

    `format=bundle` (the default) is a zip holding `world.json` plus every mesh
    and image the rows reference — the one to move between machines.
    `format=json` is the manifest alone: small, readable, and enough on a
    machine that already has the files.
    """
    try:
        rows = store.list_generations()
    except PersistenceError as e:
        raise _loud(e) from e

    if format == "json":
        return worldio.manifest(rows)

    data, report = worldio.build_bundle(rows)
    log.info(
        "exported %d row(s), %d file(s), %.1f MB",
        report["rows"], report["files"], len(data) / 1e6,
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="scorched-world-{_slug_now()}.zip"',
            # So a caller knows what it got without unzipping it.
            "X-World-Rows": str(report["rows"]),
            "X-World-Files": str(report["files"]),
            "X-World-Missing-Files": str(len(report["missing_files"])),
        },
    )


async def _import_payload(request: Request) -> bytes:
    """The bundle bytes, from a multipart `bundle` field or the raw body."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("bundle") or form.get("file")
        if not isinstance(upload, UploadFile):
            raise BundleError("multipart upload needs a 'bundle' file field")
        data = await upload.read(MAX_IMPORT_BYTES + 1)
    else:
        data = await request.body()
    if not data:
        raise BundleError("empty request body")
    if len(data) > MAX_IMPORT_BYTES:
        raise BundleError("bundle is larger than 1 GB")
    return data


@router.post("/import")
async def import_world(
    request: Request,
    mode: str = Query("merge", pattern="^(merge|replace)$"),
    store: GenerationStore = Depends(get_store),
    trash_path: Path = Depends(get_trash_path),
) -> dict:
    """Read a bundle back in. Send the zip as multipart `bundle`, or JSON as the body.

    `mode=merge` (the default) adds what is missing and leaves the rest alone —
    a row whose id is already present is skipped, so importing the same bundle
    twice is a no-op. `mode=replace` clears the world first, and stashes what it
    cleared so `/api/world/undo` can walk it back.
    """
    try:
        data = await _import_payload(request)
        body, archive = worldio.read_manifest(data)
        rows = worldio.parse_rows(body)
    except BundleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not rows:
        raise HTTPException(status_code=400, detail="bundle holds no generations")

    file_report = {}
    if archive is not None:
        try:
            file_report = worldio.unpack_files(archive)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"could not write bundle files: {e}") from e

    cleared = 0
    try:
        if mode == "replace":
            existing = store.list_generations()
            trash.stash(
                trash_path, existing,
                action="import-replace",
                label=f"the world before importing {len(rows)} generation(s)",
            )
            cleared = store.delete_all()
        # Rewrite `/outputs/...` onto this server's base before the rows land,
        # so an imported world renders here rather than pointing at whichever
        # machine exported it.
        restored = store.restore_generations(worldio.absolutize(rows))
    except PersistenceError as e:
        raise _loud(e) from e

    log.info("imported %d/%d row(s) (mode=%s, cleared=%d)", restored, len(rows), mode, cleared)
    return {
        "mode": mode,
        "in_bundle": len(rows),
        "imported": restored,
        "skipped_already_present": len(rows) - restored,
        "cleared": cleared,
        "undoable": mode == "replace" and cleared > 0,
        **file_report,
    }


@router.post("/seed")
def seed_world(
    mode: str = Query("merge", pattern="^(merge|replace)$"),
    store: GenerationStore = Depends(get_store),
    trash_path: Path = Depends(get_trash_path),
) -> dict:
    """Fill an empty world with the committed demo buildings.

    Everything it loads references `backend/assets/samples/`, which is in the
    repo, so this works on a fresh clone that has generated nothing and has no
    network — which is the state a demo machine is in more often than anyone
    plans for.
    """
    try:
        rows = worldio.load_seed_world()
    except BundleError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    cleared = 0
    try:
        if mode == "replace":
            existing = store.list_generations()
            trash.stash(
                trash_path, existing,
                action="seed-replace",
                label="the world before seeding the demo buildings",
            )
            cleared = store.delete_all()
        restored = store.restore_generations(worldio.absolutize(rows))
    except PersistenceError as e:
        raise _loud(e) from e

    log.info("seeded %d/%d demo row(s) (mode=%s)", restored, len(rows), mode)
    return {
        "mode": mode,
        "available": len(rows),
        "imported": restored,
        "skipped_already_present": len(rows) - restored,
        "cleared": cleared,
        "undoable": mode == "replace" and cleared > 0,
    }


@router.get("/undo")
def peek_undo(trash_path: Path = Depends(get_trash_path)) -> dict:
    """What undo would put back. `available: false` when there is nothing."""
    entry = trash.peek(trash_path)
    return {"available": entry is not None, **(entry or {})}


@router.post("/undo")
def undo(
    store: GenerationStore = Depends(get_store),
    trash_path: Path = Depends(get_trash_path),
) -> dict:
    """Put the last removed batch back, verbatim.

    404 rather than a quiet success when there is nothing stashed: "undo did
    nothing" and "undo restored your world" must not look the same to the UI.
    """
    taken = trash.take(trash_path)
    if taken is None:
        raise HTTPException(status_code=404, detail="nothing to undo")
    rows, meta = taken
    try:
        restored = store.restore_generations(rows)
    except PersistenceError as e:
        # Put it back in the stash: a failed undo must stay undoable.
        trash.stash(
            trash_path, rows,
            action=str(meta.get("action") or "unknown"),
            label=str(meta.get("label") or ""),
        )
        raise _loud(e) from e
    log.info("undo restored %d/%d row(s) from %s", restored, len(rows), meta.get("action"))
    return {
        "restored": restored,
        "in_batch": len(rows),
        "skipped_already_present": len(rows) - restored,
        **meta,
    }

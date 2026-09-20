"""Export a world to a portable bundle, and read one back in.

The problem this solves: a stored row points at its mesh and images by absolute
URL — `http://localhost:8000/outputs/meshes/<sha>.glb` — and those files live
in `backend/outputs/`, which is gitignored and 350 MB. Carrying the database
alone to another machine gives you eighteen rows that all render nothing.

So a bundle is a zip: `world.json` plus every file the rows actually reference.
Inside it, URLs are stored **base-relative** (`/outputs/...`, `/assets/...`) and
rewritten onto the importing server's own base on the way in, which is what
makes a bundle work on a machine whose PUBLIC_BASE_URL is not this one's.

Files under `backend/assets/` are committed to the repo, so they are referenced
but never packed — that is what keeps the seed world small enough to commit.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ..generation import config as gen_config
from ..models import Generation

log = logging.getLogger("scorched.worldio")

BUNDLE_VERSION = 1
MANIFEST_NAME = "world.json"
FILES_PREFIX = "files/"
# The URL fields on a row that can point at a file this server serves.
URL_FIELDS = ("source_photo", "artifact", "mesh_url")
ASSETS_DIR = gen_config.BACKEND_DIR / "assets"
SEED_WORLD = ASSETS_DIR / "seed-world.json"

# An import writes whatever the zip contains into outputs/, so it is bounded on
# both axes: a bundle cannot be a zip bomb and cannot be a file dump.
MAX_BUNDLE_BYTES = 1024 * 1024 * 1024      # 1 GB compressed
MAX_UNPACKED_BYTES = 3 * 1024 * 1024 * 1024  # 3 GB unpacked
MAX_MEMBERS = 5000


class BundleError(ValueError):
    """A bundle that cannot be trusted or cannot be read."""


# --- URL rewriting -------------------------------------------------------


def to_relative(url: str | None) -> str | None:
    """`http://host/outputs/x` -> `/outputs/x`. External URLs pass through."""
    if not url:
        return url
    if url.startswith("/"):
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    if parsed.path.startswith(("/outputs/", "/assets/")):
        return parsed.path
    return url


def to_absolute(url: str | None, base: str | None = None) -> str | None:
    """`/outputs/x` -> `http://this-server/outputs/x`. Absolute URLs pass through."""
    if not url or not url.startswith("/"):
        return url
    return f"{(base or gen_config.PUBLIC_BASE_URL).rstrip('/')}{url}"


def _rewrite(row: Generation, fn) -> Generation:
    d = row.model_dump(mode="json")
    for field in URL_FIELDS:
        d[field] = fn(d.get(field))
    return Generation(**d)


def relativize(rows: list[Generation]) -> list[Generation]:
    return [_rewrite(r, to_relative) for r in rows]


def absolutize(rows: list[Generation], base: str | None = None) -> list[Generation]:
    return [_rewrite(r, lambda u: to_absolute(u, base)) for r in rows]


# --- Export --------------------------------------------------------------


def _local_file_for(relative_url: str | None) -> Path | None:
    """The file on disk behind a `/outputs/...` URL, if it is really there.

    `/assets/...` deliberately returns None: those files are in the repo, so a
    bundle references them and does not carry a copy.
    """
    if not relative_url or not relative_url.startswith("/outputs/"):
        return None
    path = (gen_config.OUTPUT_DIR / relative_url[len("/outputs/"):]).resolve()
    out = gen_config.OUTPUT_DIR.resolve()
    if out not in path.parents or not path.is_file():
        return None
    return path


def manifest(rows: list[Generation]) -> dict:
    """The metadata half of a bundle — also the whole of a `format=json` export."""
    return {
        "version": BUNDLE_VERSION,
        "kind": "scorched-nebraska-world",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_base_url": gen_config.PUBLIC_BASE_URL,
        "count": len(rows),
        "generations": [r.model_dump(mode="json") for r in relativize(rows)],
    }


def build_bundle(rows: list[Generation]) -> tuple[bytes, dict]:
    """Zip the manifest plus every referenced `outputs/` file. Returns (zip, report)."""
    relative = relativize(rows)
    wanted: dict[str, Path] = {}
    missing: list[str] = []
    for row in relative:
        for field in URL_FIELDS:
            url = getattr(row, field, None)
            if not url or not url.startswith("/outputs/"):
                continue
            path = _local_file_for(url)
            if path is None:
                missing.append(url)
            else:
                wanted[url] = path

    buf = io.BytesIO()
    packed_bytes = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(
            MANIFEST_NAME,
            json.dumps(
                {
                    **manifest(rows),
                    "files": sorted(wanted),
                    "missing_files": sorted(set(missing)),
                },
                indent=1,
            ),
        )
        for url, path in sorted(wanted.items()):
            # `/outputs/meshes/x.glb` -> `files/outputs/meshes/x.glb`
            z.write(path, f"{FILES_PREFIX}{url.lstrip('/')}")
            packed_bytes += path.stat().st_size

    report = {
        "rows": len(rows),
        "files": len(wanted),
        # A missing file is reported rather than failing the export: a bundle of
        # the rows is still worth having, and the caller deserves to know which
        # buildings will come back without a mesh.
        "missing_files": sorted(set(missing)),
        "bytes_packed": packed_bytes,
    }
    if missing:
        log.warning("export: %d referenced file(s) not on disk", len(set(missing)))
    return buf.getvalue(), report


# --- Import --------------------------------------------------------------


def _safe_member_path(name: str) -> Path | None:
    """Resolve a zip member to a path under OUTPUT_DIR, or None if it escapes.

    Zip entries are attacker-controlled the moment a bundle comes from anywhere
    but this machine, and `../../.ssh/authorized_keys` is a normal-looking
    member name. Anything that does not land under outputs/ is dropped.
    """
    if not name.startswith(FILES_PREFIX):
        return None
    rel = name[len(FILES_PREFIX):]
    if not rel.startswith("outputs/"):
        return None
    out = gen_config.OUTPUT_DIR.resolve()
    target = (out / rel[len("outputs/"):]).resolve()
    if target != out and out not in target.parents:
        return None
    return target


def read_manifest(data: bytes) -> tuple[dict, zipfile.ZipFile | None]:
    """Accept either a zip bundle or a bare JSON manifest."""
    if data[:2] == b"PK":
        if len(data) > MAX_BUNDLE_BYTES:
            raise BundleError("bundle is larger than 1 GB")
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise BundleError(f"not a readable zip: {e}") from e
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS:
            raise BundleError(f"bundle holds {len(infos)} entries, over the {MAX_MEMBERS} cap")
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise BundleError("bundle unpacks to more than 3 GB")
        try:
            body = json.loads(z.read(MANIFEST_NAME))
        except KeyError as e:
            raise BundleError(f"bundle has no {MANIFEST_NAME}") from e
        except json.JSONDecodeError as e:
            raise BundleError(f"{MANIFEST_NAME} is not valid JSON: {e}") from e
        return body, z
    try:
        body = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise BundleError(f"not a zip bundle and not valid JSON: {e}") from e
    return body, None


def parse_rows(body: dict | list) -> list[Generation]:
    """Rows out of a manifest. A bare list is accepted — that is what a raw
    `GET /api/generations` dump looks like, and people will paste one in."""
    raw = body.get("generations", []) if isinstance(body, dict) else body
    if not isinstance(raw, list):
        raise BundleError("`generations` must be a list")
    rows: list[Generation] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise BundleError(f"generation {i} is not an object")
        try:
            rows.append(Generation(**item))
        except Exception as e:  # noqa: BLE001 - surfaced with its index, not swallowed
            raise BundleError(f"generation {i} ({item.get('address', '?')}): {e}") from e
    return rows


def unpack_files(z: zipfile.ZipFile) -> dict:
    """Write the bundle's files into OUTPUT_DIR. Returns a small report."""
    written = skipped = rejected = 0
    for info in z.infolist():
        if info.is_dir():
            continue
        target = _safe_member_path(info.filename)
        if target is None:
            log.warning("import: rejected bundle member %r", info.filename)
            rejected += 1
            continue
        if target.exists() and target.stat().st_size == info.file_size:
            # Storage is content-addressed by sha, so a same-size match at the
            # same name is the same bytes. Re-importing is cheap.
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        with z.open(info) as src, open(tmp, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
        tmp.replace(target)
        written += 1
    return {"files_written": written, "files_already_present": skipped, "files_rejected": rejected}


def load_seed_world() -> list[Generation]:
    """The committed demo world: eight halls built off `backend/assets/samples/`.

    Every URL in it points at `/assets/...`, which the repo carries, so this
    works on a clone that has never generated anything.
    """
    if not SEED_WORLD.is_file():
        raise BundleError(f"no seed world at {SEED_WORLD}")
    try:
        body = json.loads(SEED_WORLD.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BundleError(f"seed world is not valid JSON: {e}") from e
    return parse_rows(body)

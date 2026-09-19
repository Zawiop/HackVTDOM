"""Content-addressed file storage + a small JSON result cache.

Files land in OUTPUT_DIR/<kind>/<sha>.<ext> and are served by the app at
PUBLIC_BASE_URL/outputs/<kind>/<sha>.<ext>. Same bytes -> same URL, so re-running a
generation never duplicates files.
"""
import hashlib
import json
import threading
from pathlib import Path
from urllib.parse import urlparse

from . import config

_cache_lock = threading.Lock()
_CACHE_FILE = config.OUTPUT_DIR / "cache.json"


def sha256(*parts: bytes | str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode() if isinstance(p, str) else p)
        h.update(b"\0")
    return h.hexdigest()


def save_bytes(data: bytes, kind: str, ext: str) -> tuple[Path, str]:
    """Write data under OUTPUT_DIR/kind and return (path, public url)."""
    name = f"{sha256(data)[:24]}.{ext.lstrip('.')}"
    path = config.OUTPUT_DIR / kind / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path, url_for(path)


def url_for(path: Path) -> str:
    rel = path.resolve().relative_to(config.OUTPUT_DIR.resolve())
    return f"{config.PUBLIC_BASE_URL}/outputs/{rel.as_posix()}"


def local_path_for_url(url: str) -> Path | None:
    """If url points at a file this server stored, return its local path."""
    base = urlparse(config.PUBLIC_BASE_URL)
    u = urlparse(url)
    if (u.scheme, u.netloc) != (base.scheme, base.netloc) or not u.path.startswith("/outputs/"):
        return None
    path = (config.OUTPUT_DIR / u.path[len("/outputs/"):]).resolve()
    if config.OUTPUT_DIR.resolve() not in path.parents or not path.is_file():
        return None
    return path


_URL_FIELDS = ("imageUrl", "meshUrl", "rawMeshUrl", "cutoutUrl")


def cache_get(key: str) -> dict | None:
    with _cache_lock:
        if not _CACHE_FILE.exists():
            return None
        entry = json.loads(_CACHE_FILE.read_text()).get(key)
    if entry is None:
        return None
    # URLs are stored base-relative so a changed PUBLIC_BASE_URL doesn't strand the cache.
    for field in _URL_FIELDS:
        if entry.get(field):
            entry[field] = config.PUBLIC_BASE_URL + entry[field]
            if local_path_for_url(entry[field]) is None:
                return None  # file was deleted out from under us
    return entry


def cache_put(key: str, value: dict) -> None:
    value = dict(value)
    for field in _URL_FIELDS:
        if value.get(field, "").startswith(config.PUBLIC_BASE_URL):
            value[field] = value[field][len(config.PUBLIC_BASE_URL):]
    with _cache_lock:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(_CACHE_FILE.read_text()) if _CACHE_FILE.exists() else {}
        data[key] = value
        tmp = _CACHE_FILE.with_suffix(".json.part")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(_CACHE_FILE)

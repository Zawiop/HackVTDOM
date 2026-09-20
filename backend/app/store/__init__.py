"""Store factory. Picks the backend from config; both satisfy GenerationStore."""
from __future__ import annotations

from functools import lru_cache

from ..config import Settings, get_settings
from .base import GenerationStore
from .errors import NotFoundError, PersistenceError
from . import trash
from .sqlite_store import SqliteStore
from .supabase_store import SupabaseStore

__all__ = [
    "GenerationStore", "PersistenceError", "NotFoundError",
    "SqliteStore", "SupabaseStore", "get_store", "build_store", "trash",
]


def build_store(cfg: Settings) -> GenerationStore:
    if cfg.store_backend == "supabase":
        return SupabaseStore(cfg.supabase_url, cfg.supabase_secret_key)
    return SqliteStore(cfg.sqlite_path)


@lru_cache(maxsize=1)
def get_store() -> GenerationStore:
    # get_settings(), not the module-level `settings` singleton: that one is
    # bound at import and cannot be re-read, so clearing the settings cache had
    # no effect here. The test suite relies on being able to redirect the store
    # away from the real database, and with a captured singleton it silently
    # could not.
    return build_store(get_settings())

"""Store factory. Picks the backend from config; both satisfy GenerationStore."""
from __future__ import annotations

from functools import lru_cache

from ..config import Settings, settings
from .base import GenerationStore
from .errors import NotFoundError, PersistenceError
from .sqlite_store import SqliteStore
from .supabase_store import SupabaseStore

__all__ = [
    "GenerationStore", "PersistenceError", "NotFoundError",
    "SqliteStore", "SupabaseStore", "get_store", "build_store",
]


def build_store(cfg: Settings) -> GenerationStore:
    if cfg.store_backend == "supabase":
        return SupabaseStore(cfg.supabase_url, cfg.supabase_secret_key)
    return SqliteStore(cfg.sqlite_path)


@lru_cache(maxsize=1)
def get_store() -> GenerationStore:
    return build_store(settings)

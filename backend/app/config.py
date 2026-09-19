"""Environment/config loading for the Scorched Nebraska backend.

Secrets live in backend/.env, which is gitignored and must never be committed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ENV_PATH = BACKEND_DIR / ".env"


def _load() -> dict[str, str]:
    """Real process env wins over .env so CI/tests can override cleanly."""
    values = {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}
    values.update({k: v for k, v in os.environ.items() if k in _KNOWN or k.startswith("SN_")})
    return values


_KNOWN = {
    "SUPABASE_URL",
    "SUPABASE_SECRET_KEY",
    "NOMINATIM_USER_AGENT",
    "GEMINI_API_KEY",
    "MAPILLARY_ACCESS_TOKEN",
    "HF_TOKEN",
}


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    sqlite_path: Path
    store_backend: str  # "supabase" | "sqlite"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)


def load_settings() -> Settings:
    env = _load()
    url = (env.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (env.get("SUPABASE_SECRET_KEY") or "").strip()

    # SN_STORE lets tests and local dev force a backend explicitly.
    forced = (env.get("SN_STORE") or os.environ.get("SN_STORE") or "").strip().lower()
    if forced in {"supabase", "sqlite"}:
        backend = forced
    else:
        backend = "supabase" if (url and key) else "sqlite"

    sqlite_path = Path(
        env.get("SN_SQLITE_PATH") or os.environ.get("SN_SQLITE_PATH") or BACKEND_DIR / "local.db"
    )
    return Settings(
        supabase_url=url,
        supabase_secret_key=key,
        sqlite_path=sqlite_path,
        store_backend=backend,
    )


settings = load_settings()

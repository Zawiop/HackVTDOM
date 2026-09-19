"""Environment/config loading.

Secrets live in backend/.env, which is gitignored and must never be committed.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Step 01: Nominatim ---
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    # Nominatim's usage policy rejects generic library user agents; this must identify the app.
    nominatim_user_agent: str = "ScorchedNebraskaVTHacks/1.0 (vthacks-team@example.com)"
    nominatim_min_interval_seconds: float = 1.0

    # --- Step 02: Overpass ---
    overpass_primary_url: str = "https://overpass-api.de/api/interpreter"
    overpass_mirror_url: str = "https://overpass.kumi.systems/api/interpreter"
    # Tried in order after the two above. All are public instances from the OSM
    # wiki's list; on 2026-09-19 the first two were down and these still answered.
    overpass_extra_mirrors: List[str] = [
        "https://overpass.private.coffee/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    overpass_backoff_seconds: float = 30.0
    overpass_timeout_seconds: float = 25.0
    # Match radius for "which building is this", and the wider pull reused by steps 08/10.
    # --- Step 03: Mapillary (free; the token is registration, not billing) ---
    # Absent token simply disables the auto-fetch convenience layer; manual
    # upload is the required path and never depends on this.
    mapillary_access_token: str = ""

    overpass_match_radius_meters: int = 50
    overpass_neighbor_radius_meters: int = 250

    # --- Step 11: persistence ---
    supabase_url: str = ""
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    sqlite_path: Path = Field(
        default=BACKEND_DIR / "local.db", validation_alias=AliasChoices("SN_SQLITE_PATH")
    )
    # Forces a backend explicitly; otherwise it follows whether Supabase is configured.
    store_override: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("SN_STORE")
    )

    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def store_backend(self) -> str:
        if self.store_override in {"supabase", "sqlite"}:
            return self.store_override
        return "supabase" if self.supabase_configured else "sqlite"

    @property
    def overpass_endpoints(self) -> List[str]:
        ordered = [self.overpass_primary_url, self.overpass_mirror_url, *self.overpass_extra_mirrors]
        return list(dict.fromkeys(u for u in ordered if u))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

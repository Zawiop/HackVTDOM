from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute, so the app behaves the same whether uvicorn is started from
        # the repo root or from backend/.
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
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

    @property
    def overpass_endpoints(self) -> List[str]:
        ordered = [self.overpass_primary_url, self.overpass_mirror_url, *self.overpass_extra_mirrors]
        return list(dict.fromkeys(u for u in ordered if u))
    # Match radius for "which building is this", and the wider pull reused by steps 08/10.
    overpass_match_radius_meters: int = 50
    overpass_neighbor_radius_meters: int = 250

    # --- Step 11: Supabase persistence ---
    supabase_url: str = ""
    # The real .env uses SUPABASE_SECRET_KEY; accept the service-role spelling too.
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "supabase_secret_key"
        ),
    )

    # Local fallback used whenever Supabase is not configured. Same schema,
    # same semantics — see app/store/.
    sn_store: str = ""  # force "supabase" or "sqlite"; empty = auto
    sn_sqlite_path: Path = BACKEND_DIR / "local.db"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def store_backend(self) -> str:
        forced = (self.sn_store or "").strip().lower()
        if forced in {"supabase", "sqlite"}:
            return forced
        return "supabase" if self.supabase_configured else "sqlite"

    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()

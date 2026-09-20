import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .startup import ensure_demo_seeded
from .routers import (
    footprint,
    generation,
    generations,
    geocode,
    health,
    photo,
    placement,
    propagate,
    worldstate,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("scorched")

settings = get_settings()


# Opt-out for local dev, where you seed manually and don't want boot blocked
# on it. On a deployed host this should stay on — see app/startup.py.
AUTO_SEED = os.environ.get("AUTO_SEED_ON_BOOT", "1").lower() not in ("0", "false", "no")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("store backend: %s", settings.store_backend)
    if not settings.supabase_configured:
        log.warning(
            "SUPABASE_URL/SUPABASE_SECRET_KEY empty -> using local SQLite at %s",
            settings.sqlite_path,
        )
    if AUTO_SEED:
        await ensure_demo_seeded()
    yield


app = FastAPI(
    title="Scorched Nebraska API",
    version="0.1.0",
    description="VTHacks 14 — address to AI-redesigned building, placed on a real map.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Steps 01-02 entry, 05-07 generation, 09/11 persistence, 10 propagate.
app.include_router(health.router, prefix="/api")
app.include_router(geocode.router, prefix="/api")
app.include_router(footprint.router, prefix="/api")
app.include_router(photo.router, prefix="/api")
app.include_router(placement.router, prefix="/api")
app.include_router(worldstate.router, prefix="/api")
app.include_router(generation.router, prefix="/api")
# These two declare their own /api prefix.
app.include_router(generations.router)
app.include_router(propagate.router)

generation.setup(app)  # /outputs + /assets static files, cutout-model warmup


@app.get("/")
def root() -> dict:
    return {"service": "scorched-nebraska", "store": settings.store_backend}

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import footprint, generations, geocode, health, propagate, stubs

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("scorched")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = get_settings()
    log.info("store backend: %s", cfg.store_backend)
    if not cfg.supabase_configured:
        log.warning(
            "SUPABASE_URL is empty -> using the local SQLite fallback at %s. "
            "Set SUPABASE_URL + SUPABASE_SECRET_KEY in backend/.env to use Supabase.",
            cfg.sn_sqlite_path,
        )
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Scorched Nebraska API",
    version="0.1.0",
    description="VTHacks 14 — address to AI-redesigned building, placed on a real map.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(geocode.router, prefix="/api")
app.include_router(footprint.router, prefix="/api")
# Steps 09-11 persistence + step 10 propagate.
app.include_router(generations.router, prefix="/api")
app.include_router(propagate.router, prefix="/api")
# Keep last: everything still unimplemented answers 501 with its spec file.
app.include_router(stubs.router, prefix="/api")

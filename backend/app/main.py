"""Scorched Nebraska backend.

Routers are auto-discovered from app/routes/*.py — each module just needs to
expose `router`. Four agents are building routes in parallel; this keeps
main.py from becoming a merge-conflict hotspot.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import routes
from .config import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("scorched")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("routers mounted: %s", ", ".join(_MOUNTED) or "(none)")
    log.info("store backend: %s", settings.store_backend)
    if not settings.supabase_configured:
        log.warning(
            "SUPABASE_URL is empty -> falling back to local SQLite at %s. "
            "Set SUPABASE_URL + SUPABASE_SECRET_KEY in backend/.env to use Supabase.",
            settings.sqlite_path,
        )
    yield


app = FastAPI(title="Scorched Nebraska API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mount_routers() -> list[str]:
    mounted = []
    for mod in pkgutil.iter_modules(routes.__path__):
        module = importlib.import_module(f"{routes.__name__}.{mod.name}")
        r = getattr(module, "router", None)
        if isinstance(r, APIRouter):
            app.include_router(r)
            mounted.append(mod.name)
    return mounted


_MOUNTED = _mount_routers()


@app.get("/")
def root() -> dict:
    return {"service": "scorched-nebraska", "routers": _MOUNTED, "store": settings.store_backend}

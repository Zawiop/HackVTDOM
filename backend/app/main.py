import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import footprint, geocode, health, stubs

logging.basicConfig(level=logging.INFO)

app = FastAPI(
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
app.include_router(stubs.router, prefix="/api")

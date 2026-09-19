from fastapi import APIRouter

from ..services import cache
from ..store import PersistenceError, get_store

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness plus which persistence backend is actually live.

    The store is reported rather than raised on: a failing database should make
    this endpoint say so loudly, not take the whole health check down with it.
    """
    try:
        store = get_store().health()
    except PersistenceError as e:
        store = {"ok": False, "error": str(e)}

    return {
        "status": "ok",
        "service": "scorched-nebraska-api",
        "footprintCacheEntries": cache.size(),
        "store": store,
    }

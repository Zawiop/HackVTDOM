from fastapi import APIRouter, Depends

from ..services import cache
from ..store import GenerationStore, PersistenceError, get_store

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(store: GenerationStore = Depends(get_store)):
    try:
        store_status = store.health()
        ok = True
    except PersistenceError as exc:
        # Report it rather than 500ing — the entry pipeline still works without a store.
        store_status = {"error": str(exc)}
        ok = False

    return {
        "status": "ok" if ok else "degraded",
        "service": "scorched-nebraska-api",
        "footprintCacheEntries": cache.size(),
        "store": store_status,
    }

from fastapi import APIRouter

from ..services import cache

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "scorched-nebraska-api", "footprintCacheEntries": cache.size()}

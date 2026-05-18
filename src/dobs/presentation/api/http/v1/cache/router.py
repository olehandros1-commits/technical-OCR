from fastapi import APIRouter, Depends, Query, status

from dobs.application.commands.cache.bust_cache import BustCacheCommand
from dobs.application.commands.cache.clear_cache import ClearCacheCommand
from dobs.application.queries.get_cache_keys import GetCacheKeysQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/cache",
    tags=["cache"],
    dependencies=[Depends(api_key_dependency)],
)


def get_cache_keys_handler():
    raise NotImplementedError("Composition root must wire GetCacheKeysHandler via dependency_overrides")


def get_bust_cache_handler():
    raise NotImplementedError("Composition root must wire BustCacheHandler via dependency_overrides")


def get_clear_cache_handler():
    raise NotImplementedError("Composition root must wire ClearCacheHandler via dependency_overrides")


@router.get("/keys")
async def get_cache_keys(
    limit: int = Query(default=200, ge=1, le=1000),
    handler=Depends(get_cache_keys_handler),
) -> dict:
    result = await handler(GetCacheKeysQuery(limit=limit))
    return {"keys": result}


@router.delete("/{key}", status_code=status.HTTP_200_OK)
async def delete_cache_key(
    key: str,
    handler=Depends(get_bust_cache_handler),
) -> dict:
    deleted = await handler(BustCacheCommand(key=key))
    return {"deleted": deleted, "key": key}


@router.post("/clear", status_code=status.HTTP_200_OK)
async def clear_cache(
    handler=Depends(get_clear_cache_handler),
) -> dict:
    count = await handler(ClearCacheCommand())
    return {"cleared": count}

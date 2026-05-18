from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query, status

from dobs.application.commands.cache.bust_cache import BustCacheCommand, BustCacheHandler
from dobs.application.commands.cache.clear_cache import ClearCacheCommand, ClearCacheHandler
from dobs.application.queries.get_cache_keys import GetCacheKeysHandler, GetCacheKeysQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/cache",
    tags=["cache"],
    route_class=DishkaRoute,
    dependencies=[Depends(api_key_dependency)],
)


@router.get("/keys")
async def get_cache_keys(
    handler: FromDishka[GetCacheKeysHandler],
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, object]:
    result = await handler(GetCacheKeysQuery(limit=limit))
    return {"keys": result}


@router.delete("/{key}", status_code=status.HTTP_200_OK)
async def delete_cache_key(
    key: str,
    handler: FromDishka[BustCacheHandler],
) -> dict[str, object]:
    deleted = await handler(BustCacheCommand(key=key))
    return {"deleted": deleted, "key": key}


@router.post("/clear", status_code=status.HTTP_200_OK)
async def clear_cache(
    handler: FromDishka[ClearCacheHandler],
) -> dict[str, object]:
    count = await handler(ClearCacheCommand())
    return {"cleared": count}

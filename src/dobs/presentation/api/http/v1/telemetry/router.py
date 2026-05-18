import dataclasses

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from dobs.application.queries.get_telemetry import GetTelemetryHandler, GetTelemetryQuery
from dobs.application.queries.get_tiers import GetTiersHandler, GetTiersQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/telemetry",
    tags=["telemetry"],
    route_class=DishkaRoute,
    dependencies=[Depends(api_key_dependency)],
)


@router.get("")
async def get_telemetry(handler: FromDishka[GetTelemetryHandler]) -> dict:
    result = await handler(GetTelemetryQuery())
    return result


@router.get("/tiers")
async def get_tiers(handler: FromDishka[GetTiersHandler]) -> dict:
    result = await handler(GetTiersQuery())
    return {"tiers": [dataclasses.asdict(t) for t in result]}

import dataclasses

from fastapi import APIRouter, Depends

from dobs.application.queries.get_telemetry import GetTelemetryQuery
from dobs.application.queries.get_tiers import GetTiersQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/telemetry",
    tags=["telemetry"],
    dependencies=[Depends(api_key_dependency)],
)


def get_telemetry_handler():
    raise NotImplementedError("Composition root must wire GetTelemetryHandler via dependency_overrides")


def get_tiers_handler():
    raise NotImplementedError("Composition root must wire GetTiersHandler via dependency_overrides")


@router.get("")
async def get_telemetry(handler=Depends(get_telemetry_handler)) -> dict:
    result = await handler(GetTelemetryQuery())
    return result


@router.get("/tiers")
async def get_tiers(handler=Depends(get_tiers_handler)) -> dict:
    result = await handler(GetTiersQuery())
    return {"tiers": [dataclasses.asdict(t) for t in result]}

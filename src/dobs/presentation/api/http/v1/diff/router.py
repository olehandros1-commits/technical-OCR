import dataclasses
from typing import Any

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from dobs.application.queries.diff_extractions import DiffExtractionsHandler, DiffExtractionsQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/diff",
    tags=["diff"],
    route_class=DishkaRoute,
    dependencies=[Depends(api_key_dependency)],
)


class DiffRequest(BaseModel):
    result_a: dict[str, Any]
    result_b: dict[str, Any]


@router.post("", status_code=status.HTTP_200_OK)
async def diff_extractions(
    body: DiffRequest,
    handler: FromDishka[DiffExtractionsHandler],
) -> dict[str, Any]:
    result = await handler(DiffExtractionsQuery(result_a=body.result_a, result_b=body.result_b))
    return dataclasses.asdict(result)

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/diff",
    tags=["diff"],
    dependencies=[Depends(api_key_dependency)],
)


class DiffRequest(BaseModel):
    result_a: dict
    result_b: dict


def get_diff_handler():
    raise NotImplementedError("Composition root must wire DiffExtractionsHandler via dependency_overrides")


@router.post("", status_code=status.HTTP_200_OK)
async def diff_extractions(
    body: DiffRequest,
    handler=Depends(get_diff_handler),
) -> dict:
    result = await handler(result_a=body.result_a, result_b=body.result_b)
    return result

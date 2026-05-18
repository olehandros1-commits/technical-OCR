from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/reviews",
    tags=["reviews"],
    dependencies=[Depends(api_key_dependency)],
)


class RecordReviewRequest(BaseModel):
    statement_key: str
    tx_index: int
    decision: str
    reviewer: str | None = None
    note: str | None = None


def get_record_review_handler():
    raise NotImplementedError("Composition root must wire RecordReviewHandler via dependency_overrides")


def get_reviews_handler():
    raise NotImplementedError("Composition root must wire GetReviewsHandler via dependency_overrides")


def get_explain_handler():
    raise NotImplementedError("Composition root must wire ExplainAnomalyHandler via dependency_overrides")


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_review(
    body: RecordReviewRequest,
    handler=Depends(get_record_review_handler),
) -> dict:
    await handler(
        statement_key=body.statement_key,
        tx_index=body.tx_index,
        decision=body.decision,
        reviewer=body.reviewer or "",
    )
    return {"ok": True}


@router.get("/{key}")
async def get_reviews(
    key: str,
    handler=Depends(get_reviews_handler),
) -> dict:
    result = await handler(statement_key=key)
    return {"decisions": result}


@router.post("/explain", status_code=status.HTTP_200_OK)
async def explain_anomaly(
    body: dict,
    handler=Depends(get_explain_handler),
) -> dict:
    result = await handler(**body)
    return result

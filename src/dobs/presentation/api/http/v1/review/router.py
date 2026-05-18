from typing import Any

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from dobs.application.commands.review.record_review import RecordReviewCommand, RecordReviewHandler
from dobs.application.ports.review_store import Decision
from dobs.application.queries.explain_anomaly import ExplainAnomalyHandler, ExplainAnomalyQuery
from dobs.application.queries.get_reviews import GetReviewsHandler, GetReviewsQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/reviews",
    tags=["reviews"],
    route_class=DishkaRoute,
    dependencies=[Depends(api_key_dependency)],
)


class RecordReviewRequest(BaseModel):
    statement_key: str
    tx_index: int
    decision: Decision
    reviewer: str | None = None
    note: str | None = None


class ExplainAnomalyRequest(BaseModel):
    anomaly: dict[str, Any]
    transaction: dict[str, Any] | None = None
    context_transactions: list[dict[str, Any]] | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_review(
    body: RecordReviewRequest,
    handler: FromDishka[RecordReviewHandler],
) -> dict[str, object]:
    await handler(
        RecordReviewCommand(
            statement_key=body.statement_key,
            tx_index=body.tx_index,
            decision=body.decision,
            reviewer=body.reviewer or "",
        )
    )
    return {"ok": True}


@router.get("/{key}")
async def get_reviews(
    key: str,
    handler: FromDishka[GetReviewsHandler],
) -> dict[str, object]:
    result = await handler(GetReviewsQuery(statement_key=key))
    return {"decisions": result}


@router.post("/explain", status_code=status.HTTP_200_OK)
async def explain_anomaly(
    body: ExplainAnomalyRequest,
    handler: FromDishka[ExplainAnomalyHandler],
) -> dict[str, object]:
    result = await handler(
        ExplainAnomalyQuery(
            anomaly=body.anomaly,
            transaction=body.transaction,
            context_transactions=body.context_transactions,
        )
    )
    return result.model_dump() if hasattr(result, "model_dump") else dict(result)

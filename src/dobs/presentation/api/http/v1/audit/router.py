from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query

from dobs.application.queries.get_audit_log import GetAuditLogHandler, GetAuditLogQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/audit",
    tags=["audit"],
    route_class=DishkaRoute,
    dependencies=[Depends(api_key_dependency)],
)


@router.get("")
async def get_audit_log(
    handler: FromDishka[GetAuditLogHandler],
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    result = await handler(GetAuditLogQuery(limit=limit))
    return {"entries": result}

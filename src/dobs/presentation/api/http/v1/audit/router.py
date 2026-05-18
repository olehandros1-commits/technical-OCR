from fastapi import APIRouter, Depends, Query

from dobs.application.queries.get_audit_log import GetAuditLogQuery
from dobs.presentation.api.http.middleware.api_key import api_key_dependency

router = APIRouter(
    prefix="/api/v1/audit",
    tags=["audit"],
    dependencies=[Depends(api_key_dependency)],
)


def get_audit_handler():
    raise NotImplementedError("Composition root must wire GetAuditLogHandler via dependency_overrides")


@router.get("")
async def get_audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    handler=Depends(get_audit_handler),
) -> dict:
    result = await handler(GetAuditLogQuery(limit=limit))
    return {"entries": result}

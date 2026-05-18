from __future__ import annotations

import os

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status

from dobs.application.ports.audit_sink import AuditSinkPort
from dobs.application.ports.cache import StatementCachePort
from dobs.main.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/health", tags=["health"], route_class=DishkaRoute)


@router.get("/live")
async def live() -> dict:
    return {"status": "live"}


@router.get("/ready")
async def ready(
    cache: FromDishka[StatementCachePort],
    audit: FromDishka[AuditSinkPort],
    response: Response,
) -> dict:
    checks: dict[str, str] = {}

    try:
        await cache.stats()
        checks["cache"] = "ok"
    except Exception as exc:
        log.warning("readiness cache probe failed", error=str(exc))
        checks["cache"] = f"fail: {exc}"

    try:
        await audit.recent(limit=1)
        checks["audit_db"] = "ok"
    except Exception as exc:
        log.warning("readiness audit probe failed", error=str(exc))
        checks["audit_db"] = f"fail: {exc}"

    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            from redis.asyncio import Redis
            client = Redis.from_url(redis_url, socket_timeout=2.0)
            await client.ping()
            await client.close()
            checks["redis"] = "ok"
        except Exception as exc:
            log.warning("readiness redis probe failed", error=str(exc))
            checks["redis"] = f"fail: {exc}"

    backend = os.getenv("EXTRACTOR_BACKEND", "anthropic")
    if backend == "anthropic":
        checks["anthropic_key"] = "configured" if os.getenv("ANTHROPIC_API_KEY") else "missing"

    all_ok = all(v == "ok" or v == "configured" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@router.get("")
async def health() -> dict:
    return {"ok": True, "service": "dobs-extractor"}

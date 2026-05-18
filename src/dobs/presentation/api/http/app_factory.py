from __future__ import annotations

from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from dobs.main.di import build_providers
from dobs.presentation.api.http.common.exc_handlers import map_exc_handlers
from dobs.presentation.api.http.middleware.cors import configured_cors
from dobs.presentation.api.http.middleware.tenant import TenantMiddleware
from dobs.presentation.api.http.v1.audit.router import router as audit_router
from dobs.presentation.api.http.v1.cache.router import router as cache_router
from dobs.presentation.api.http.v1.diff.router import router as diff_router
from dobs.presentation.api.http.v1.extraction.router import router as extraction_router
from dobs.presentation.api.http.v1.health.router import router as health_router
from dobs.presentation.api.http.v1.review.router import router as review_router
from dobs.presentation.api.http.v1.telemetry.router import router as telemetry_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="dobs — Bank Statement Extractor",
        version="1.0.0",
        description=(
            "Extract reconciled structured JSON from bank statement PDFs. "
            "Hybrid deterministic + LLM pipeline with anomaly detection, "
            "HITL review, multi-tenant isolation, and async SSE job streaming."
        ),
    )

    app.include_router(health_router)
    app.include_router(extraction_router)
    app.include_router(audit_router)
    app.include_router(cache_router)
    app.include_router(telemetry_router)
    app.include_router(review_router)
    app.include_router(diff_router)

    map_exc_handlers(app)
    configured_cors(app)
    app.add_middleware(TenantMiddleware)

    container = make_async_container(*build_providers())
    setup_dishka(container=container, app=app)

    return app

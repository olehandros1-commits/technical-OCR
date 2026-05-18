from __future__ import annotations

from fastapi import FastAPI

from dobs.presentation.api.http.common.exc_handlers import map_exc_handlers
from dobs.presentation.api.http.middleware.cors import configured_cors
from dobs.presentation.api.http.middleware.tenant import TenantMiddleware
from dobs.presentation.api.http.v1.audit.router import get_audit_handler
from dobs.presentation.api.http.v1.audit.router import router as audit_router
from dobs.presentation.api.http.v1.cache.router import (
    get_bust_cache_handler,
    get_cache_keys_handler,
    get_clear_cache_handler,
)
from dobs.presentation.api.http.v1.cache.router import router as cache_router
from dobs.presentation.api.http.v1.diff.router import get_diff_handler
from dobs.presentation.api.http.v1.diff.router import router as diff_router
from dobs.presentation.api.http.v1.extraction.router import get_extract_handler
from dobs.presentation.api.http.v1.extraction.router import router as extraction_router
from dobs.presentation.api.http.v1.health.router import router as health_router
from dobs.presentation.api.http.v1.review.router import (
    get_explain_handler,
    get_record_review_handler,
    get_reviews_handler,
)
from dobs.presentation.api.http.v1.review.router import router as review_router
from dobs.presentation.api.http.v1.telemetry.router import (
    get_telemetry_handler,
    get_tiers_handler,
)
from dobs.presentation.api.http.v1.telemetry.router import router as telemetry_router


def create_app(
    dependency_overrides: dict | None = None,
    *,
    container=None,
) -> FastAPI:
    from dobs.main.composition_root import Container, build_container

    if container is None:
        container = build_container()

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

    app.dependency_overrides[get_extract_handler] = lambda: container.extract_handler()
    app.dependency_overrides[get_audit_handler] = lambda: container.get_audit_log_handler()
    app.dependency_overrides[get_cache_keys_handler] = lambda: container.get_cache_keys_handler()
    app.dependency_overrides[get_bust_cache_handler] = lambda: container.bust_cache_handler()
    app.dependency_overrides[get_clear_cache_handler] = lambda: container.clear_cache_handler()
    app.dependency_overrides[get_telemetry_handler] = lambda: container.get_telemetry_handler()
    app.dependency_overrides[get_tiers_handler] = lambda: container.get_tiers_handler()
    app.dependency_overrides[get_record_review_handler] = lambda: container.record_review_handler()
    app.dependency_overrides[get_reviews_handler] = lambda: container.get_reviews_handler()
    app.dependency_overrides[get_explain_handler] = lambda: container.explain_anomaly_handler()
    app.dependency_overrides[get_diff_handler] = lambda: container.diff_handler()

    if dependency_overrides:
        app.dependency_overrides.update(dependency_overrides)

    return app

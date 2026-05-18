from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from dobs.infrastructure.adapters.jobs.background_runner import BackgroundJobRunner
from dobs.main.config.settings import get_settings
from dobs.main.di import build_providers
from dobs.main.logging_setup import configure_logging, get_logger
from dobs.presentation.api.http.common.exc_handlers import map_exc_handlers
from dobs.presentation.api.http.middleware.cors import configured_cors
from dobs.presentation.api.http.middleware.request_id import RequestIdMiddleware
from dobs.presentation.api.http.middleware.tenant import TenantMiddleware
from dobs.presentation.api.http.v1.audit.router import router as audit_router
from dobs.presentation.api.http.v1.cache.router import router as cache_router
from dobs.presentation.api.http.v1.diff.router import router as diff_router
from dobs.presentation.api.http.v1.extraction.router import router as extraction_router
from dobs.presentation.api.http.v1.health.router import router as health_router
from dobs.presentation.api.http.v1.review.router import router as review_router
from dobs.presentation.api.http.v1.telemetry.router import router as telemetry_router

log = get_logger(__name__)


def _maybe_setup_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.getenv("SENTRY_ENV", "dev"),
        )
    except ImportError:
        pass


def _maybe_setup_otel(app: FastAPI) -> None:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument()
        except ImportError:
            pass
    except ImportError:
        pass


def _maybe_setup_metrics(app: FastAPI) -> None:
    if os.getenv("DOBS_DISABLE_METRICS"):
        return
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    except ImportError:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    _maybe_setup_sentry()

    container = make_async_container(*build_providers())

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("api startup")
        yield
        async with container() as scope:
            runner = await scope.get(BackgroundJobRunner)
            await runner.shutdown()
        await container.close()
        log.info("api shutdown")

    app = FastAPI(
        title="dobs — Bank Statement Extractor",
        version="1.0.0",
        description=(
            "Extract reconciled structured JSON from bank statement PDFs. "
            "Hybrid deterministic + LLM pipeline with anomaly detection, "
            "HITL review, multi-tenant isolation, and async SSE job streaming."
        ),
        lifespan=_lifespan,
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
    app.add_middleware(RequestIdMiddleware)

    _maybe_setup_otel(app)
    _maybe_setup_metrics(app)

    setup_dishka(container=container, app=app)
    return app

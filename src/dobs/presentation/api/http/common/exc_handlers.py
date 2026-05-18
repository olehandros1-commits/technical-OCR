from functools import partial

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dobs.domain.errors import (
    DomainError,
    ExtractionJobNotFoundError,
    InvalidPeriodError,
    InvalidTransactionError,
    ReconciliationError,
    StatementAlreadyCachedError,
)
from dobs.main.logging_setup import get_logger, request_id_ctx

log = get_logger(__name__)


def _domain_error_handler(request: Request, exc: DomainError, status_code: int) -> JSONResponse:
    log.warning(
        "domain error",
        path=str(request.url.path),
        status=status_code,
        error_type=type(exc).__name__,
        message=exc.message,
    )
    return JSONResponse(
        {"detail": exc.message, "request_id": request_id_ctx.get()},
        status_code=status_code,
    )


def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception(
        "unhandled exception",
        path=str(request.url.path),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        {"detail": "Internal server error", "request_id": request_id_ctx.get()},
        status_code=500,
    )


def map_exc_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ExtractionJobNotFoundError, partial(_domain_error_handler, status_code=404))
    app.add_exception_handler(StatementAlreadyCachedError, partial(_domain_error_handler, status_code=409))
    app.add_exception_handler(InvalidPeriodError, partial(_domain_error_handler, status_code=422))
    app.add_exception_handler(InvalidTransactionError, partial(_domain_error_handler, status_code=422))
    app.add_exception_handler(ReconciliationError, partial(_domain_error_handler, status_code=422))
    app.add_exception_handler(Exception, _internal_error_handler)

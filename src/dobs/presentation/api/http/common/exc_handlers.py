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


def _error_handler(request: Request, exc: DomainError, status_code: int) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=status_code)


def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


def map_exc_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        ExtractionJobNotFoundError,
        partial(_error_handler, status_code=404),
    )
    app.add_exception_handler(
        StatementAlreadyCachedError,
        partial(_error_handler, status_code=409),
    )
    app.add_exception_handler(
        InvalidPeriodError,
        partial(_error_handler, status_code=422),
    )
    app.add_exception_handler(
        InvalidTransactionError,
        partial(_error_handler, status_code=422),
    )
    app.add_exception_handler(
        ReconciliationError,
        partial(_error_handler, status_code=422),
    )
    app.add_exception_handler(Exception, _internal_error_handler)

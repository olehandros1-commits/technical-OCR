from __future__ import annotations

import logging
from contextvars import ContextVar

import structlog

request_id_ctx: ContextVar[str | None] = ContextVar("dobs_request_id", default=None)


def _inject_request_id(_, __, event_dict):
    rid = request_id_ctx.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    logging.basicConfig(level=level, format="%(message)s")

    processors = [
        structlog.contextvars.merge_contextvars,
        _inject_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)

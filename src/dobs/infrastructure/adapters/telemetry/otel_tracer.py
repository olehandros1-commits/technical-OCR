from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger(__name__)

_INITIALISED = False
_TRACER = None


def _init_tracer() -> object | None:
    global _INITIALISED, _TRACER
    if _INITIALISED:
        return _TRACER
    _INITIALISED = True

    if os.getenv("EXTRACTOR_TRACING", "0") not in {"1", "true", "yes"}:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        log.info("OpenTelemetry SDK not installed; tracing disabled")
        return None

    provider = TracerProvider(resource=Resource.create({
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "bank-statement-extractor"),
    }))

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            log.info("OTLP trace exporter -> %s", otlp_endpoint)
        except ImportError:
            log.warning("OTLP exporter requested but not installed")
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("dobs")
    return _TRACER


class OpenTelemetryTracer:
    def __init__(self, /) -> None:
        pass

    @contextmanager
    def span(self, name: str, attributes: dict | None = None) -> Iterator[object | None]:
        tracer = _init_tracer()
        if tracer is None:
            yield None
            return
        with tracer.start_as_current_span(name) as sp:
            if attributes:
                for k, v in attributes.items():
                    try:
                        sp.set_attribute(k, v)
                    except Exception:
                        sp.set_attribute(k, str(v))
            try:
                yield sp
            except Exception as exc:
                sp.record_exception(exc)
                raise

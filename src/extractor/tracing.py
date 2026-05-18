"""OpenTelemetry tracing for the pipeline.

Why:
  Cost / token telemetry tells you what you spent overall. Distributed
  tracing tells you WHERE the time went per request -- per stage, per
  statement, per chunk -- so you can see at a glance that, say, the
  repair loop on the November statement is the long pole.

Default exporter is a ConsoleSpanExporter (zero config, prints to stderr).
Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318/v1/traces` to send to
a real collector. The pipeline doesn't care which exporter is active.

Convention:
    with span("extract.summary", attributes={"label": "Apr 2025"}):
        ...
"""
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
        # Tracing off by default. Spans become no-ops -- the pipeline stays
        # equally fast, no exporter races with pytest's captured stderr,
        # and demos that want spans set EXTRACTOR_TRACING=1.
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    except ImportError:
        log.info("OpenTelemetry SDK not installed; tracing disabled")
        return None

    provider = TracerProvider(resource=Resource.create({
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "bank-statement-extractor"),
    }))

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            log.info("OTLP trace exporter -> %s", otlp_endpoint)
        except ImportError:
            log.warning("OTLP exporter requested but not installed")
    else:
        # Console exporter -- handy for `streamlit run` / `uvicorn --reload`
        # developer loops. SimpleSpanProcessor flushes synchronously so we
        # don't leave background threads racing with interpreter shutdown.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("extractor")
    return _TRACER


@contextmanager
def span(name: str, attributes: dict | None = None) -> Iterator[object | None]:
    """Open a span if tracing is enabled, otherwise a no-op."""
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

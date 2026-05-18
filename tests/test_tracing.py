"""Tests for the OpenTelemetry tracing wrapper.

We don't assert exported spans -- we just confirm the API is a safe no-op
when tracing is off (the default) and that the context manager works.
"""
from extractor.tracing import span


def test_span_is_noop_when_disabled():
    # EXTRACTOR_TRACING is not set in the test environment, so the tracer
    # initialiser returns None and `span` yields None without raising.
    with span("x", {"k": "v"}) as sp:
        assert sp is None


def test_span_does_not_break_on_exception():
    raised = False
    try:
        with span("x"):
            raise RuntimeError("expected")
    except RuntimeError:
        raised = True
    assert raised

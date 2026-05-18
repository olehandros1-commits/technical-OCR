from dobs.infrastructure.adapters.telemetry.otel_tracer import OpenTelemetryTracer


def test_span_is_noop_when_disabled():
    tracer = OpenTelemetryTracer()
    with tracer.span("x", {"k": "v"}) as sp:
        assert sp is None


def test_span_does_not_break_on_exception():
    tracer = OpenTelemetryTracer()
    raised = False
    try:
        with tracer.span("x"):
            raise RuntimeError("expected")
    except RuntimeError:
        raised = True
    assert raised

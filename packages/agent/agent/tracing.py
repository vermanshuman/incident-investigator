"""OpenTelemetry spans around the agent's own work.

Instrumenting the investigator (rather than offering OTel as an integration)
is what makes a slow or expensive run diagnosable: one trace per run, with a
span per graph node, model call and tool call carrying tokens, cost and
latency.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set, so nothing is required to run
the project. `OTEL_CONSOLE=1` prints spans instead, which is enough to show
the shape without running a collector.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_tracer: Any = None
_configured = False


def _configure() -> Any:
    global _tracer, _configured
    if _configured:
        return _tracer
    _configured = True

    endpoint, console = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"), os.getenv("OTEL_CONSOLE")
    if not endpoint and not console:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "incident-investigator-agent"),
        }))
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        if console:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("agent")
    except Exception:  # noqa: BLE001 - telemetry must never break a run
        _tracer = None
    return _tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """A span when tracing is on, a no-op when it is not."""
    tracer = _configure()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


def set_attributes(current: Any, **attributes: Any) -> None:
    if current is None:
        return
    for key, value in attributes.items():
        if value is not None:
            current.set_attribute(key, value)


def record_error(current: Any, exc: BaseException) -> None:
    if current is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        current.record_exception(exc)
        current.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
    except Exception:  # noqa: BLE001 - telemetry must never break a run
        return

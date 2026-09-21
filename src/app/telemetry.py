"""Standard OTel instrumentation and a thread-free Cloudflare Logs exporter."""

import hashlib
import json
import logging
import sys
import traceback
from collections.abc import Mapping, Sequence

from opentelemetry import trace
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

SERVICE_NAME = "wellnest-backend"
NANOSECONDS_PER_MILLISECOND = 1_000_000
PROPAGATOR = TraceContextTextMapPropagator()
SAFE_ATTRIBUTES = frozenset(
    {
        "http.method",
        "http.request.method",
        "http.route",
        "http.status_code",
        "http.response.status_code",
        "db.system",
        "db.system.name",
        "db.operation.name",
        "messaging.system",
        "messaging.destination.name",
        "messaging.message.id",
        "messaging.delivery.age_ms",
        "messaging.delivery.action",
        "messaging.delivery.attempt",
    }
)
logger = logging.getLogger(__name__)
_initialized = False


def span_record(span: ReadableSpan) -> dict:
    values = span.attributes or {}
    attributes = {k: v for k, v in values.items() if k in SAFE_ATTRIBUTES}
    # SQL literals, bind parameters, URLs, headers and exception messages are never exported.
    statement = values.get("db.statement") or values.get("db.query.text")
    if statement:
        attributes["db.query.fingerprint"] = hashlib.sha256(str(statement).encode()).hexdigest()
    return {
        "event": "otel.span",
        "service_name": SERVICE_NAME,
        "trace_id": format(span.context.trace_id, "032x"),
        "span_id": format(span.context.span_id, "016x"),
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
        "name": span.name,
        "links": [
            {
                "trace_id": format(link.context.trace_id, "032x"),
                "span_id": format(link.context.span_id, "016x"),
            }
            for link in span.links
        ],
        "kind": span.kind.name,
        "start_time_unix_nano": str(span.start_time),
        "end_time_unix_nano": str(span.end_time),
        "duration_ms": (span.end_time - span.start_time) / NANOSECONDS_PER_MILLISECOND,
        "status": span.status.status_code.name,
        "exception_types": [
            event.attributes.get("exception.type")
            for event in span.events
            if event.name == "exception" and event.attributes
        ],
        "attributes": attributes,
    }


class CloudflareLogExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            for span in spans:
                logger.info("%s", span.name, extra={"span_record": span_record(span)})
        except Exception:
            # Observability failure must never fail the transaction being observed.
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


class TraceLogFormatter(logging.Formatter):
    def format(self, record):
        context = trace.get_current_span().get_span_context()
        payload = {
            "event": "application.log",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": format(context.trace_id, "032x") if context.is_valid else None,
            "span_id": format(context.span_id, "016x") if context.is_valid else None,
        }
        if hasattr(record, "span_record"):
            payload.update(record.span_record)
        if record.exc_info and record.exc_info[0]:
            # Retain locations without exception messages, source lines or local values.
            payload["exception_type"] = record.exc_info[0].__name__
            payload["frames"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(payload, ensure_ascii=True)


def current_headers() -> dict[str, str]:
    carrier: dict[str, str] = {}
    PROPAGATOR.inject(carrier)
    return carrier


def extracted_context(headers: Mapping[str, str]):
    return PROPAGATOR.extract(headers)


def message_links(headers: Mapping[str, str]):
    context = trace.get_current_span(extracted_context(headers)).get_span_context()
    return [trace.Link(context)] if context.is_valid else []


def tracer():
    return trace.get_tracer(SERVICE_NAME)


def configure_telemetry(app):
    global _initialized
    if not _initialized:
        # Resource.create uses environment detectors; an explicit Resource avoids thread workers.
        provider = TracerProvider(
            resource=Resource({"service.name": SERVICE_NAME}), shutdown_on_exit=False
        )
        provider.add_span_processor(SimpleSpanProcessor(CloudflareLogExporter()))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        AsyncPGInstrumentor().instrument()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(TraceLogFormatter())
        logging.getLogger("app").addHandler(handler)
        logging.getLogger("app").propagate = False
        logging.getLogger("app").setLevel(logging.INFO)
        _initialized = True
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=r".*/health(?:\?.*)?$,.*/ready(?:\?.*)?$",
        exclude_spans=["receive", "send"],
    )

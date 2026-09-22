import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import AsyncOpenTelemetryTransport
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select
from test_payments import workflow as workflow
from test_queue_delivery import Message

from app.domain.payment_states import PaymentTask
from app.domain.queue_message import DeliveryResult, PaymentMessage
from app.models import Outbox
from app.repositories.outbox import OutboxRepository
from app.telemetry import CloudflareLogExporter, current_headers, span_record, tracer
from app.worker_runtime import QueuePublisher, consume_batch

RECORDER = InMemorySpanExporter()
trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(RECORDER))


@pytest.fixture
def spans():
    RECORDER.clear()
    yield RECORDER
    RECORDER.clear()


async def test_concurrent_http_requests_have_isolated_database_children(client, spans):
    responses = await asyncio.gather(client.post("/api/sessions"), client.post("/api/sessions"))
    ids = [r.headers["x-trace-id"] for r in responses]
    assert len(set(ids)) == 2
    records = [span_record(s) for s in spans.get_finished_spans()]
    for trace_id in ids:
        branch = [r for r in records if r["trace_id"] == trace_id]
        server = next(r for r in branch if r["kind"] == "SERVER")
        queries = [r for r in branch if r["attributes"].get("db.system") == "postgresql"]
        assert queries and all(q["parent_span_id"] == server["span_id"] for q in queries)


async def test_custom_http_transport_propagates_w3c_context(spans):
    headers = {}

    async def receive(request):
        headers.update(request.headers)
        return httpx.Response(200)

    with tracer().start_as_current_span("caller") as parent:
        transport = AsyncOpenTelemetryTransport(httpx.MockTransport(receive))
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://internal.invalid/token-must-not-be-logged")
    child = next(s for s in spans.get_finished_spans() if s.name == "GET")
    assert child.parent.span_id == parent.context.span_id
    assert headers["traceparent"].split("-")[1:3] == [
        format(parent.context.trace_id, "032x"),
        format(child.context.span_id, "016x"),
    ]
    assert "token-must-not-be-logged" not in json.dumps(span_record(child))


async def test_durable_outbox_keeps_origin_across_unrelated_relay(workflow, spans, monkeypatch):
    outbox = OutboxRepository(workflow.db)
    aggregate = uuid4()
    with tracer().start_as_current_span("confirmation") as root:
        await outbox.enqueue(PaymentTask.create, aggregate)
        expected_parent = current_headers()
    row = await workflow.db.fetchrow(
        select(Outbox).select_from(Outbox).where(Outbox.aggregate_id == aggregate)
    )
    assert json.loads(row["headers"]) == expected_parent
    sent = []

    async def send(body):
        sent.append(body)

    with tracer().start_as_current_span("unrelated-cron"):
        await QueuePublisher(SimpleNamespace(send=send)).publish(
            PaymentMessage(
                event_id=row["id"], lease_token=uuid4(), headers=json.loads(row["headers"])
            )
        )

    async def dispatch(env, path, payload):
        assert trace.get_current_span().get_span_context().trace_id == root.context.trace_id
        return DeliveryResult()

    monkeypatch.setattr("app.worker_runtime.dispatch", dispatch)
    monkeypatch.setattr("app.worker_runtime.load_payment_settings", lambda env: workflow.settings)
    message = Message(sent[0])
    await consume_batch(SimpleNamespace(messages=[message]), None)
    producer = next(s for s in spans.get_finished_spans() if s.kind.name == "PRODUCER")
    consumer = next(s for s in spans.get_finished_spans() if s.kind.name == "CONSUMER")
    assert producer.parent.span_id == root.context.span_id
    assert consumer.parent.span_id == producer.context.span_id
    assert consumer.context.trace_id == root.context.trace_id
    assert consumer.links[0].context.span_id == producer.context.span_id
    assert span_record(consumer)["links"][0]["span_id"] == format(producer.context.span_id, "016x")
    assert message.acked and not message.retries
    assert consumer.attributes["messaging.delivery.age_ms"] >= 0


def test_export_redacts_parameters_urls_and_exception_details(spans):
    with tracer().start_as_current_span("SELECT") as span:
        span.set_attribute("db.statement", "SELECT 'private-health-data'")
        span.set_attribute("http.url", "https://host/secret-token")
        span.set_attribute("db.user", "private-user")
        span.record_exception(ValueError("private-error-message"))
    record = span_record(spans.get_finished_spans()[-1])
    encoded = json.dumps(record)
    assert "private" not in encoded and "secret-token" not in encoded
    assert record["exception_types"] == ["ValueError"]
    assert len(record["attributes"]["db.query.fingerprint"]) == 64


def test_export_failure_cannot_break_business(spans, monkeypatch):
    with tracer().start_as_current_span("transaction"):
        pass

    def broken(*args, **kwargs):
        raise OSError("stdout unavailable")

    monkeypatch.setattr("app.telemetry.logger.info", broken)
    assert CloudflareLogExporter().export(spans.get_finished_spans()) == SpanExportResult.FAILURE


def test_headers_preserve_tracestate_and_reject_invalid_parent():
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

    from app.telemetry import current_headers, extracted_context

    parent = SpanContext(
        1,
        2,
        is_remote=True,
        trace_flags=TraceFlags(1),
        trace_state=TraceState([("vendor", "opaque")]),
    )
    with trace.use_span(NonRecordingSpan(parent)):
        headers = current_headers()
    restored = trace.get_current_span(extracted_context(headers)).get_span_context()
    assert restored.trace_id == 1 and restored.trace_state.get("vendor") == "opaque"
    invalid = trace.get_current_span(extracted_context({"traceparent": "invalid"}))
    assert not invalid.get_span_context().is_valid


def test_structured_logging_has_trace_and_safe_exception_locations(spans):
    import logging
    import sys

    from app.telemetry import TraceLogFormatter

    with tracer().start_as_current_span("request") as parent:
        try:
            raise ValueError("secret-password-and-health-data")
        except ValueError:
            record = logging.LogRecord(
                "app.test", logging.ERROR, __file__, 1, "Operation failed", (), sys.exc_info()
            )
            encoded = TraceLogFormatter().format(record)
    payload = json.loads(encoded)
    assert payload["trace_id"] == format(parent.context.trace_id, "032x")
    assert payload["exception_type"] == "ValueError" and payload["frames"]
    assert payload["level"] == "ERROR"
    assert "secret-password" not in encoded
    assert "raise ValueError" not in encoded


async def test_unhandled_failure_is_json_and_does_not_expose_exception():
    from fastapi import FastAPI

    from app.middleware import RequestPolicy

    app = FastAPI()
    app.add_middleware(RequestPolicy)

    @app.get("/failure")
    async def failure():
        raise RuntimeError("password=private")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/failure")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["requestId"] == response.headers["x-request-id"]
    assert "private" not in response.text
    assert response.headers["cache-control"] == "no-store"

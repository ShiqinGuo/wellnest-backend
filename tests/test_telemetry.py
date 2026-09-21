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
from test_payments import workflow as workflow
from test_queue_delivery import Message

from app.domain.payment_states import PaymentTask
from app.domain.queue_message import DeliveryResult, PaymentMessage
from app.repositories.outbox import OutboxRepository
from app.telemetry import CloudflareLogExporter, current_traceparent, span_record, tracer
from app.worker_runtime import QueuePublisher, consume_batch

RECORDER = InMemorySpanExporter()
trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(RECORDER))


@pytest.fixture
def spans():
    RECORDER.clear()
    yield RECORDER
    RECORDER.clear()


async def test_concurrent_http_requests_have_isolated_database_children(client, spans):
    responses = await asyncio.gather(client.post('/api/sessions'), client.post('/api/sessions'))
    ids = [r.headers['x-trace-id'] for r in responses]
    assert len(set(ids)) == 2
    records = [span_record(s) for s in spans.get_finished_spans()]
    for trace_id in ids:
        branch = [r for r in records if r['trace_id'] == trace_id]
        server = next(r for r in branch if r['kind'] == 'SERVER')
        queries = [r for r in branch if r['attributes'].get('db.system') == 'postgresql']
        assert queries and all(q['parent_span_id'] == server['span_id'] for q in queries)


async def test_custom_http_transport_propagates_w3c_context(spans):
    headers = {}

    async def receive(request):
        headers.update(request.headers)
        return httpx.Response(200)

    with tracer().start_as_current_span('caller') as parent:
        transport = AsyncOpenTelemetryTransport(httpx.MockTransport(receive))
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get('https://internal.invalid/token-must-not-be-logged')
    child = next(s for s in spans.get_finished_spans() if s.name == 'GET')
    assert child.parent.span_id == parent.context.span_id
    assert headers['traceparent'].split('-')[1:3] == [
        format(parent.context.trace_id, '032x'), format(child.context.span_id, '016x')
    ]
    assert 'token-must-not-be-logged' not in json.dumps(span_record(child))


async def test_durable_outbox_keeps_origin_across_unrelated_relay(workflow, spans, monkeypatch):
    outbox = OutboxRepository(workflow.db)
    aggregate = uuid4()
    with tracer().start_as_current_span('confirmation') as root:
        await outbox.enqueue(PaymentTask.create, aggregate)
        expected_parent = current_traceparent()
    row = await workflow.db.fetchrow('SELECT * FROM outbox_events WHERE aggregate_id=$1', aggregate)
    assert row['traceparent'] == expected_parent
    sent = []

    async def send(body):
        sent.append(body)

    with tracer().start_as_current_span('unrelated-cron'):
        await QueuePublisher(SimpleNamespace(send=send)).publish(PaymentMessage(
            event_id=row['id'], lease_token=uuid4(), traceparent=row['traceparent']
        ))

    async def dispatch(env, path, payload):
        assert trace.get_current_span().get_span_context().trace_id == root.context.trace_id
        return DeliveryResult()

    monkeypatch.setattr('app.worker_runtime.dispatch', dispatch)
    monkeypatch.setattr('app.worker_runtime.load_payment_settings', lambda env: workflow.settings)
    message = Message(sent[0])
    await consume_batch(SimpleNamespace(messages=[message]), None)
    producer = next(s for s in spans.get_finished_spans() if s.kind.name == 'PRODUCER')
    consumer = next(s for s in spans.get_finished_spans() if s.kind.name == 'CONSUMER')
    assert producer.parent.span_id == root.context.span_id
    assert consumer.parent.span_id == producer.context.span_id
    assert consumer.context.trace_id == root.context.trace_id
    assert message.acked and not message.retries
    assert consumer.attributes['messaging.delivery.age_ms'] >= 0


def test_export_redacts_parameters_urls_and_exception_details(spans):
    with tracer().start_as_current_span('SELECT') as span:
        span.set_attribute('db.statement', "SELECT 'private-health-data'")
        span.set_attribute('http.url', 'https://host/secret-token')
        span.set_attribute('db.user', 'private-user')
        span.record_exception(ValueError('private-error-message'))
    record = span_record(spans.get_finished_spans()[-1])
    encoded = json.dumps(record)
    assert 'private' not in encoded and 'secret-token' not in encoded
    assert record['exception_types'] == ['ValueError']
    assert len(record['attributes']['db.query.fingerprint']) == 64


def test_export_failure_cannot_break_business(spans, monkeypatch):
    with tracer().start_as_current_span('transaction'):
        pass

    def broken(*args, **kwargs):
        raise OSError('stdout unavailable')

    monkeypatch.setattr('builtins.print', broken)
    assert CloudflareLogExporter().export(spans.get_finished_spans()) == SpanExportResult.FAILURE

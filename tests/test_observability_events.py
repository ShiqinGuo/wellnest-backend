import json
import logging

import pytest
from test_flows import complete, key
from test_payments import checkout, notification, payment, post_notification, run
from test_payments import workflow as workflow

from app.domain.payment_states import PaymentTask
from app.log_events import LogEvent, business_event
from app.repositories.command import CommandRepository
from app.telemetry import TraceLogFormatter


@pytest.fixture
def events():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(json.loads(TraceLogFormatter().format(record)))

    handler = Capture()
    logger = logging.getLogger("app.log_events")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


async def test_request_summary_correlates_validation_origin_and_not_found(client, events):
    await client.post("/api/sessions")
    created = await client.post("/api/assessments", json={}, headers=key())
    path = f"/api/assessments/{created.json()['id']}"
    events.clear()
    invalid = await client.patch(
        path, json={"expectedVersion": 0, "answers": {"age": "not-an-age"}}, headers=key()
    )
    rejected = await client.patch(path, json={}, headers={"Origin": "https://evil.example"})
    missing = await client.get("/does-not-exist")
    summaries = [e for e in events if e["event"] == LogEvent.request_completed]
    assert [e["status_code"] for e in summaries] == [422, 403, 404]
    for summary, response in zip(summaries, [invalid, rejected, missing], strict=True):
        assert summary["trace_id"] == response.headers["x-trace-id"]
        assert summary["request_id"] == response.headers["x-request-id"]
        assert summary["span_id"] and summary["timestamp"]
        assert summary["response_complete"] and summary["duration_ms"] >= 0
    assert summaries[0]["error_details"]["issues"][0]["field"] == "body.answers.age"
    assert "not-an-age" not in json.dumps(summaries)
    assert summaries[0]["route"] == "/api/assessments/{assessment_id}"


async def test_events_only_after_commit_and_never_after_rollback(workflow, events):
    with pytest.raises(RuntimeError, match="rollback"):
        async with workflow.db.transaction():
            business_event(LogEvent.subscription_activated, payment_id="rolled-back")
            assert not events
            raise RuntimeError("rollback")
    assert not events
    async with workflow.db.transaction():
        business_event(LogEvent.subscription_activated, payment_id="committed")
        assert not events
    assert [e["payment_id"] for e in events] == ["committed"]


async def test_payment_rollback_does_not_claim_creation(client, events, monkeypatch):
    await complete(client)
    events.clear()

    async def fail(*args, **kwargs):
        raise RuntimeError("receipt failed")

    monkeypatch.setattr(CommandRepository, "record", fail)
    response = await client.post("/api/payments", json={}, headers=key())
    assert response.status_code == 500
    assert not any(e["event"] == LogEvent.payment_created for e in events)
    assert events[-1]["event"] == LogEvent.request_completed
    assert events[-1]["error_code"] == "INTERNAL_ERROR"


async def test_payment_results_and_duplicate_delivery_emit_activation_once(
    client, workflow, events
):
    payment_id, _ = await payment(client)
    transaction_id = await checkout(client, workflow, payment_id)
    assert not any(e["event"] == LogEvent.subscription_activated for e in events)
    await run(workflow, PaymentTask.deliver_webhook, transaction_id)
    payload = await notification(workflow, transaction_id)
    processed = await run(workflow, PaymentTask.process_webhook, payload.event_id)
    await post_notification(client, workflow, payload)
    await workflow.execute(processed)
    for event in (
        LogEvent.payment_created,
        LogEvent.provider_confirmed,
        LogEvent.payment_transitioned,
        LogEvent.subscription_activated,
        LogEvent.webhook_processed,
    ):
        matching = [e for e in events if e["event"] == event]
        assert len(matching) == 1, (event, matching)
        assert matching[0]["payment_id"] == str(payment_id)


async def test_log_sink_failure_does_not_break_committed_transaction(workflow, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("log sink unavailable")

    monkeypatch.setattr("app.log_events.logger.info", fail)
    async with workflow.db.transaction():
        business_event(LogEvent.command_committed, command="test")

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_payments import workflow as workflow

from app.domain.payment_states import PaymentTask
from app.domain.queue_message import PaymentMessage
from app.services.payment_delivery import PaymentDelivery
from app.worker_runtime import consume_batch


class Publisher:
    def __init__(self):
        self.messages = []
        self.error = None

    async def publish(self, message):
        self.messages.append(message)
        if self.error:
            raise self.error


async def prepare(flow):
    event_id = uuid4()
    await flow.db.execute(
        """INSERT INTO outbox_events(id,task,aggregate_id,status,available_at)
        VALUES($1,$2,$3,'pending','1990-01-01')""",
        event_id,
        PaymentTask.create,
        uuid4(),
    )
    flow.settings = flow.settings.model_copy(update={"batch_size": 1})
    publisher = Publisher()
    service = PaymentDelivery(flow, publisher)
    return event_id, publisher, service


async def test_publish_timeout_keeps_durable_event_and_fences_late_delivery(workflow):
    event_id, publisher, service = await prepare(workflow)
    publisher.error = TimeoutError("accepted but response lost")
    await service.relay()
    old = publisher.messages[0]
    row = await service.outbox.get(event_id)
    assert row["status"] == "pending" and row["last_error"] == "TimeoutError"
    await service.db.execute(
        "UPDATE outbox_events SET available_at='1990-01-01' WHERE id=$1", event_id
    )
    publisher.error = None
    await service.relay()
    new = publisher.messages[-1]
    assert new.lease_token != old.lease_token
    assert await service.consume(old) is None
    row = await service.outbox.get(event_id)
    assert row["processed_at"] is None and row["lease_token"] == new.lease_token


async def test_execution_retry_is_bounded_and_preserves_failure(workflow):
    event_id, publisher, service = await prepare(workflow)
    service.settings = workflow.settings.model_copy(update={"max_attempts": 2})
    await service.relay()
    message = publisher.messages[0]
    # The missing payment is a real execution failure, not a mocked handler.
    assert await service.consume(message) == service.settings.retry_base
    row = await service.outbox.get(event_id)
    assert row["attempts"] == 2 and row["last_error"] == "ValueError"
    assert await service.consume(message) is None
    row = await service.outbox.get(event_id)
    assert row["status"] == "failed" and row["processed_at"] is None
    assert await service.outbox.requeue(event_id)
    # Old queue messages cannot execute an operator-requeued event.
    assert await service.consume(message) is None
    assert (await service.outbox.get(event_id))["attempts"] == 0


async def test_commit_before_ack_and_late_publish_confirmation(workflow):
    event_id, publisher, service = await prepare(workflow)
    row = await service.outbox.claim(service.settings)
    await service.outbox.done(event_id)
    await service.outbox.published(row)
    message = PaymentMessage(event_id=event_id, lease_token=row["lease_token"])
    assert await service.consume(message) is None
    assert (await service.outbox.get(event_id))["processed_at"] is not None


async def test_stale_publish_cannot_resurrect_exhausted_event(workflow):
    event_id, _, service = await prepare(workflow)
    row = await service.outbox.claim(service.settings)
    await service.outbox.failed(
        row, "Exhausted", service.settings.model_copy(update={"max_attempts": 1})
    )
    await service.outbox.published(row)
    assert (await service.outbox.get(event_id))["status"] == "failed"


class Message:
    def __init__(self, body):
        self.id = str(uuid4())
        self.body = body
        self.acked = False
        self.retries = []

    def ack(self):
        self.acked = True

    def retry(self, **options):
        self.retries.append(options)


async def test_batch_poison_does_not_retry_successful_sibling(monkeypatch, workflow):
    event_id, publisher, service = await prepare(workflow)
    await service.relay()
    await service.outbox.done(event_id)
    valid = Message(publisher.messages[0].model_dump_json())
    poison = Message('{"event_id":"invalid"}')
    monkeypatch.setattr("app.worker_runtime.delivery", lambda env: service)
    await consume_batch(SimpleNamespace(messages=[poison, valid]), None)
    assert valid.acked and not valid.retries
    assert poison.retries and not poison.acked


async def test_database_outage_does_not_ack(monkeypatch):
    async def broken(payload):
        raise ConnectionError("database unavailable")

    async def release():
        pass

    async def relay(env):
        pass

    service = SimpleNamespace(
        consume=broken,
        db=SimpleNamespace(release=release),
        settings=SimpleNamespace(retry_base=2),
    )
    monkeypatch.setattr("app.worker_runtime.delivery", lambda env: service)
    monkeypatch.setattr("app.worker_runtime.safe_relay", relay)
    message = Message(PaymentMessage(event_id=uuid4(), lease_token=uuid4()).model_dump_json())
    await consume_batch(SimpleNamespace(messages=[message]), None)
    assert not message.acked and message.retries == [{"delaySeconds": 2}]


@pytest.mark.parametrize("extra", [{"version": 2}, {"user_id": "spoofed"}, {"task": "arbitrary"}])
def test_message_rejects_unknown_schema_and_commands(extra):
    with pytest.raises(ValidationError):
        PaymentMessage.model_validate(
            {"event_id": str(uuid4()), "lease_token": str(uuid4()), **extra}
        )

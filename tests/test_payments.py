import asyncio
import time
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from test_flows import complete, key

from app.database import ScopedDatabase
from app.domain.payment import ChannelNotification
from app.domain.payment_states import PaymentEvent, PaymentStateMachine, PaymentStatus, PaymentTask
from app.errors import AppError
from app.main import app
from app.payment_settings import payment_settings
from app.providers.mock_payment import MockPaymentGateway, sign, verify
from app.repositories.outbox import OutboxRepository
from app.services.payment_workflow import PaymentWorkflow


@pytest.fixture
async def workflow(client, database_url):
    db = ScopedDatabase(lambda: asyncpg.connect(database_url))
    settings = app.dependency_overrides[payment_settings]()
    flow = PaymentWorkflow(db, settings, MockPaymentGateway(settings, httpx.ASGITransport(app)))
    try:
        yield flow
    finally:
        await db.release()


async def payment(client):
    assessment = await complete(client)
    response = await client.post("/api/payments", json={}, headers=key())
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["nextAction"] == "wait"
    assert response.json()["checkoutUrl"] is None
    return UUID(response.json()["id"]), assessment


async def run(flow, task, aggregate_id):
    event_id = await flow.db.fetchval(
        "SELECT id FROM outbox_events WHERE task=$1 AND aggregate_id=$2 "
        "AND processed_at IS NULL ORDER BY created_at LIMIT 1",
        task,
        aggregate_id,
    )
    assert event_id is not None
    await flow.execute(event_id)
    return event_id


async def checkout(client, flow, payment_id, outcome="succeeded"):
    await run(flow, PaymentTask.create, payment_id)
    response = await client.get(f"/api/payments/{payment_id}")
    assert response.json()["nextAction"] == "open_checkout"
    result = await client.post(
        response.json()["checkoutUrl"] + "/confirm", json={"outcome": outcome}
    )
    assert result.status_code == 200
    return UUID(result.json()["transaction_id"])


async def notification(flow, transaction_id):
    row = await flow.db.fetchrow("SELECT * FROM mock_provider_payments WHERE id=$1", transaction_id)
    view = await flow.gateway.query(row["merchant_payment_id"])
    return ChannelNotification(**view.model_dump(), event_id=row["event_id"])


async def post_notification(client, flow, payload, timestamp=None, signature=None):
    body = payload.model_dump_json().encode()
    timestamp = timestamp or str(int(time.time()))
    return await client.post(
        "/api/webhooks/payments/mock",
        content=body,
        headers={
            "X-Payment-Timestamp": timestamp,
            "X-Payment-Signature": signature
            or sign(body, timestamp, flow.settings.webhook_secret.get_secret_value()),
        },
    )


async def test_real_callback_boundary_and_repeated_delivery(client, workflow):
    payment_id, assessment = await payment(client)
    transaction_id = await checkout(client, workflow, payment_id)
    path = f"/api/assessments/{assessment['id']}/result"
    assert (await client.get(path)).json()["access"] == "free"
    # Mock provider has succeeded, but cannot directly grant merchant membership.
    assert (await client.get(f"/api/payments/{payment_id}")).json()["status"] == "pending"
    deliver = await run(workflow, PaymentTask.deliver_webhook, transaction_id)
    payload = await notification(workflow, transaction_id)
    assert (await post_notification(client, workflow, payload)).status_code == 200
    assert (await client.get(path)).json()["access"] == "free"
    processed = await run(workflow, PaymentTask.process_webhook, payload.event_id)
    await workflow.execute(deliver)
    await workflow.execute(processed)
    assert (await client.get(path)).json()["access"] == "member"
    view = (await client.get(f"/api/payments/{payment_id}")).json()
    assert view["status"] == "succeeded" and view["nextAction"] == "none"
    assert "userId" not in view and "providerTransactionId" not in view
    assert (
        await workflow.db.fetchval(
            "SELECT count(*) FROM subscriptions WHERE source_payment_id=$1",
            payment_id,
        )
        == 1
    )


async def test_lost_callback_query_and_missing_channel_create_recover(client, workflow):
    payment_id, _ = await payment(client)
    # Creation task was lost: reconciliation first queries, then idempotently creates.
    await client.post(f"/api/payments/{payment_id}/refresh")
    await run(workflow, PaymentTask.reconcile, payment_id)
    query = await workflow.gateway.query(payment_id)
    await client.post(query.checkout_url + "/confirm", json={})
    # Deliberately do NOT dispatch the provider callback.
    await workflow.db.execute("UPDATE payments SET next_check_at=now() WHERE id=$1", payment_id)
    for _ in range(100):
        if not await workflow.schedule_reconciliation():
            break
    await run(workflow, PaymentTask.reconcile, payment_id)
    assert (await client.get(f"/api/payments/{payment_id}")).json()["status"] == "succeeded"
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "active"


async def test_timeout_after_provider_created_does_not_duplicate_or_fail(client, workflow):
    payment_id, _ = await payment(client)
    original = workflow.gateway.create

    async def create_then_timeout(command):
        await original(command)
        raise httpx.ReadTimeout("Injected response loss")

    workflow.gateway.create = create_then_timeout
    with pytest.raises(httpx.ReadTimeout):
        await run(workflow, PaymentTask.create, payment_id)
    assert (await client.get(f"/api/payments/{payment_id}")).json()["status"] == "pending"
    workflow.gateway.create = original
    await run(workflow, PaymentTask.create, payment_id)
    assert (
        await workflow.db.fetchval(
            "SELECT count(*) FROM mock_provider_payments WHERE merchant_payment_id=$1",
            payment_id,
        )
        == 1
    )


@pytest.mark.parametrize("outcome", ["failed", "closed"])
async def test_channel_terminal_states_never_grant_membership(client, workflow, outcome):
    payment_id, _ = await payment(client)
    await run(workflow, PaymentTask.create, payment_id)
    if outcome == "closed":
        await workflow.db.execute(
            "UPDATE mock_provider_payments SET expires_at=now()-interval '1 second' "
            "WHERE merchant_payment_id=$1",
            payment_id,
        )
        view = await workflow.gateway.query(payment_id)
        assert view.status == PaymentStatus.closed
        result = await client.post(view.checkout_url + "/confirm", json={})
        assert result.json()["status"] == "closed"
    else:
        view = await workflow.gateway.query(payment_id)
        await client.post(view.checkout_url + "/confirm", json={"outcome": outcome})
    await client.post(f"/api/payments/{payment_id}/refresh")
    await run(workflow, PaymentTask.reconcile, payment_id)
    assert (await client.get(f"/api/payments/{payment_id}")).json()["status"] == outcome
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "inactive"
    assert (await client.post("/api/payments", json={}, headers=key())).status_code == 201


async def test_webhook_signature_replay_mismatch_and_no_bare_route(client, workflow):
    payment_id, _ = await payment(client)
    transaction_id = await checkout(client, workflow, payment_id)
    payload = await notification(workflow, transaction_id)
    assert (
        await post_notification(client, workflow, payload, signature="invalid")
    ).status_code == 401
    assert (await post_notification(client, workflow, payload, timestamp="1")).status_code == 401
    assert (await client.post("/pay", json={}, headers=key())).status_code == 404
    assert (await client.get(f"/api/mock-provider/payments/{payment_id}")).status_code == 401
    headers = workflow.gateway.headers()
    assert (
        await client.get(
            f"/api/mock-provider/payments/{payment_id}",
            headers=headers,
        )
    ).json()["status"] == "succeeded"
    bad = payload.model_copy(update={"amount_minor": payload.amount_minor + 1})
    assert (await post_notification(client, workflow, bad)).status_code == 200
    assert (await post_notification(client, workflow, payload)).status_code == 409
    await run(workflow, PaymentTask.process_webhook, bad.event_id)
    row = await workflow.db.fetchrow(
        "SELECT * FROM payment_webhook_inbox WHERE id=$1", bad.event_id
    )
    assert row["status"] == "rejected" and row["rejection_code"] == "PAYMENT_MISMATCH"
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "inactive"
    # A rejected notification does not prevent authoritative query recovery.
    await client.post(f"/api/payments/{payment_id}/refresh")
    await run(workflow, PaymentTask.reconcile, payment_id)
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "active"


async def test_foreign_user_cannot_read_refresh_or_set_price(client, workflow):
    payment_id, _ = await payment(client)
    for body in ({"amountMinor": 1}, {"userId": str(uuid4())}, {"planId": "other"}):
        assert (await client.post("/api/payments", json=body, headers=key())).status_code == 422
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as other:
        assert (await other.get(f"/api/payments/{payment_id}")).status_code == 401
        await other.post("/api/sessions")
        assert (await other.get(f"/api/payments/{payment_id}")).status_code == 404
        assert (await other.post(f"/api/payments/{payment_id}/refresh")).status_code == 404


async def test_callback_and_query_race_preserve_one_entitlement(client, workflow, database_url):
    payment_id, _ = await payment(client)
    transaction_id = await checkout(client, workflow, payment_id)
    await run(workflow, PaymentTask.deliver_webhook, transaction_id)
    payload = await notification(workflow, transaction_id)
    await client.post(f"/api/payments/{payment_id}/refresh")
    other_db = ScopedDatabase(lambda: asyncpg.connect(database_url))
    other = PaymentWorkflow(other_db, workflow.settings, workflow.gateway)
    try:
        await asyncio.gather(
            run(workflow, PaymentTask.process_webhook, payload.event_id),
            run(other, PaymentTask.reconcile, payment_id),
        )
    finally:
        await other_db.release()
    assert (
        await workflow.db.fetchval(
            "SELECT count(*) FROM subscriptions WHERE source_payment_id=$1",
            payment_id,
        )
        == 1
    )


async def test_transaction_failure_keeps_inbox_and_payment_retryable(client, workflow, monkeypatch):
    payment_id, _ = await payment(client)
    transaction_id = await checkout(client, workflow, payment_id)
    await run(workflow, PaymentTask.deliver_webhook, transaction_id)
    payload = await notification(workflow, transaction_id)
    original = workflow.outbox.done

    async def fail(event_id):
        raise RuntimeError("Injected commit-phase failure")

    monkeypatch.setattr(workflow.outbox, "done", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        await run(workflow, PaymentTask.process_webhook, payload.event_id)
    assert (await client.get(f"/api/payments/{payment_id}")).json()["status"] == "pending"
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "inactive"
    assert (
        await workflow.db.fetchval(
            "SELECT status FROM payment_webhook_inbox WHERE id=$1",
            payload.event_id,
        )
        == "pending"
    )
    monkeypatch.setattr(workflow.outbox, "done", original)
    await run(workflow, PaymentTask.process_webhook, payload.event_id)
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "active"


def test_payment_machine_rejects_terminal_regression():
    assert (
        PaymentStateMachine.transition(PaymentStatus.pending, PaymentEvent.succeed) == "succeeded"
    )
    assert (
        PaymentStateMachine.transition(PaymentStatus.succeeded, PaymentEvent.succeed) == "succeeded"
    )
    with pytest.raises(AppError):
        PaymentStateMachine.transition(PaymentStatus.succeeded, PaymentEvent.fail)


@pytest.mark.parametrize("timestamp,signature", [("1", "invalid"), ("bad", "bad"), (None, "é")])
def test_invalid_signature_is_rejected_without_server_error(client, timestamp, signature):
    settings = app.dependency_overrides[payment_settings]()
    with pytest.raises(AppError) as rejected:
        verify(b"{}", timestamp or str(int(time.time())), signature, settings)
    assert rejected.value.status == 401


async def test_outbox_lease_recovery_and_bounded_failures(client, workflow):
    # Directly target a fresh event; other tests may have deliberately pending events.
    event_id = uuid4()
    await workflow.db.execute(
        """INSERT INTO outbox_events(id,task,aggregate_id,status,available_at)
        VALUES($1,$2,$3,'pending','2000-01-01')""",
        event_id,
        PaymentTask.create,
        uuid4(),
    )
    outbox = OutboxRepository(workflow.db)
    row = await outbox.claim(workflow.settings)
    assert row["id"] == event_id and row["attempts"] == 1
    await outbox.published(row)
    # Simulate publish succeeded but worker disappeared; lease expiry makes it deliverable again.
    await workflow.db.execute("UPDATE outbox_events SET lease_until=now() WHERE id=$1", event_id)
    reclaimed = await outbox.claim(workflow.settings)
    assert reclaimed["id"] == event_id and reclaimed["lease_token"] != row["lease_token"]
    await outbox.failed(row, "StalePublisher", workflow.settings)
    assert (await outbox.get(event_id))["lease_token"] == reclaimed["lease_token"]
    await outbox.failed(
        reclaimed, "BrokerUnavailable", workflow.settings.model_copy(update={"max_attempts": 2})
    )
    assert (await outbox.get(event_id))["status"] == "failed"
    assert await outbox.requeue(event_id)
    assert (await outbox.get(event_id))["status"] == "pending"


def test_openapi_documents_webhook_body_and_only_prefixed_payment_routes():
    schema = app.openapi()
    body = schema["paths"]["/api/webhooks/payments/mock"]["post"]["requestBody"]
    properties = body["content"]["application/json"]["schema"]["properties"]
    assert {
        "event_id",
        "merchant_payment_id",
        "transaction_id",
        "status",
        "amount_minor",
    } <= properties.keys()
    assert "/pay" not in schema["paths"]
    assert "PaymentStatus" in schema["components"]["schemas"]

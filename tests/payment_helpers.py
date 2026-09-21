"""Payment integration harness: real PostgreSQL + HTTP contracts, no broker scheduling."""

from uuid import UUID, uuid4

import httpx

from app.dependencies.database import connection
from app.main import app
from app.payment_settings import payment_settings
from app.providers.mock_payment import MockPaymentGateway
from app.services.payment_workflow import PaymentWorkflow


async def settle(client, payment_id: str):
    async for db in app.dependency_overrides[connection]():
        settings = app.dependency_overrides[payment_settings]()
        workflow = PaymentWorkflow(
            db, settings, MockPaymentGateway(settings, httpx.ASGITransport(app))
        )
        payment_uuid = UUID(payment_id)
        create = await db.fetchval(
            "SELECT id FROM outbox_events WHERE aggregate_id=$1 AND task='payment.create'",
            payment_uuid,
        )
        await workflow.execute(create)
        view = (await client.get(f"/api/payments/{payment_id}")).json()
        response = await client.post(view["checkoutUrl"] + "/confirm", json={})
        assert response.status_code == 200, response.text
        transaction_id = UUID(response.json()["transaction_id"])
        deliver = await db.fetchval(
            "SELECT id FROM outbox_events WHERE aggregate_id=$1 AND task='mock.deliver_webhook'",
            transaction_id,
        )
        await workflow.execute(deliver)
        notification_id = await db.fetchval(
            "SELECT event_id FROM mock_provider_payments WHERE id=$1",
            transaction_id,
        )
        process = await db.fetchval(
            "SELECT id FROM outbox_events WHERE aggregate_id=$1 AND task='payment.process_webhook'",
            notification_id,
        )
        await workflow.execute(process)


async def pay(client):
    response = await client.post(
        "/api/payments",
        json={},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    await settle(client, response.json()["id"])
    return response

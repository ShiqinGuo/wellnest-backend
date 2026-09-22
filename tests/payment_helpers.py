"""Payment integration harness: real PostgreSQL + HTTP contracts, no broker scheduling."""

from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from app.composition import build_payment_workflow
from app.dependencies.database import connection
from app.main import app
from app.models import MockProviderPayment, Outbox
from app.payment_settings import payment_settings
from app.providers.mock_payment import MockPaymentGateway


async def settle(client, payment_id: str):
    async for db in app.dependency_overrides[connection]():
        settings = app.dependency_overrides[payment_settings]()
        workflow = build_payment_workflow(
            db, settings, MockPaymentGateway(settings, httpx.ASGITransport(app))
        )
        payment_uuid = UUID(payment_id)
        create = await db.fetchval(
            select(Outbox.id)
            .select_from(Outbox)
            .where(Outbox.aggregate_id == payment_uuid, Outbox.task == "payment.create")
        )
        await workflow.execute(create)
        view = (await client.get(f"/api/payments/{payment_id}")).json()
        response = await client.post(view["checkoutUrl"] + "/confirm", json={})
        assert response.status_code == 200, response.text
        transaction_id = UUID(response.json()["transaction_id"])
        deliver = await db.fetchval(
            select(Outbox.id)
            .select_from(Outbox)
            .where(Outbox.aggregate_id == transaction_id, Outbox.task == "mock.deliver_webhook")
        )
        await workflow.execute(deliver)
        notification_id = await db.fetchval(
            select(MockProviderPayment.event_id)
            .select_from(MockProviderPayment)
            .where(MockProviderPayment.id == transaction_id)
        )
        process = await db.fetchval(
            select(Outbox.id)
            .select_from(Outbox)
            .where(Outbox.aggregate_id == notification_id, Outbox.task == "payment.process_webhook")
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

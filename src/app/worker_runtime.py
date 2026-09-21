"""Cloudflare adapters; payment services remain independent of the Worker SDK."""

import logging

import httpx
from pydantic import ValidationError

from app.domain.queue_message import DeliveryResult, PaymentMessage
from app.payment_settings import load_payment_settings
from app.providers.mock_payment import MockPaymentGateway
from app.providers.worker_http import ServiceBindingTransport
from app.runtime_database import scoped_database
from app.services.payment_delivery import PaymentDelivery
from app.services.payment_workflow import PaymentWorkflow

logger = logging.getLogger(__name__)


class QueuePublisher:
    def __init__(self, binding):
        self.binding = binding

    async def publish(self, message: PaymentMessage) -> None:
        # A JSON string crosses the Python/JS boundary without leaking proxy objects.
        await self.binding.send(message.model_dump_json())


def delivery(env) -> PaymentDelivery:
    settings = load_payment_settings(env)
    db = scoped_database(env)
    gateway = MockPaymentGateway(
        settings, ServiceBindingTransport(env.PAYMENT_API, settings.network_timeout)
    )
    return PaymentDelivery(PaymentWorkflow(db, settings, gateway), QueuePublisher(env.PAYMENTS))


async def relay(env, *, reconcile: bool = False) -> None:
    service = delivery(env)
    try:
        await service.relay(reconcile=reconcile)
    finally:
        await service.db.release()


async def safe_relay(env) -> None:
    try:
        await relay(env)
    except Exception as exc:
        # The transaction is already durable. Cron recovers even if waitUntil is cut short.
        logger.error("Outbox relay deferred to recovery: %s", type(exc).__name__)


async def dispatch(env, path: str, payload: PaymentMessage | None = None) -> DeliveryResult:
    """Fetch placement applies here; Queue and Cron entrypoints never open a DB connection."""
    settings = load_payment_settings(env)
    if settings.internal_key is None:
        raise RuntimeError("Payment internal key is not configured")
    transport = ServiceBindingTransport(env.PAYMENT_API, settings.dispatch_timeout)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            f"https://payment.internal/_internal/payments/{path}",
            headers={"Authorization": f"Bearer {settings.internal_key.get_secret_value()}"},
            json=payload.model_dump(mode="json") if payload else None,
        )
        response.raise_for_status()
        return DeliveryResult.model_validate_json(response.content)


async def consume_batch(batch, env) -> None:
    settings = load_payment_settings(env)
    for message in batch.messages:
        try:
            payload = PaymentMessage.model_validate_json(message.body)
        except (ValidationError, TypeError):
            logger.error("Invalid payment queue message: id=%s", message.id)
            message.retry()
            continue
        try:
            result = await dispatch(env, "consume", payload)
            if result.retry_after is None:
                message.ack()
            else:
                message.retry(delaySeconds=result.retry_after)
        except Exception as exc:
            # A lost HTTP response may follow a committed transaction: retry the same lease.
            logger.error(
                "Payment queue unavailable: event=%s error=%s", payload.event_id, type(exc).__name__
            )
            message.retry(delaySeconds=settings.retry_base)

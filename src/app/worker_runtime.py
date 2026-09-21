"""Cloudflare adapters; payment services remain independent of the Worker SDK."""

import logging

from pydantic import ValidationError

from app.domain.queue_message import PaymentMessage
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


async def consume_batch(batch, env) -> None:
    for message in batch.messages:
        try:
            payload = PaymentMessage.model_validate_json(message.body)
        except (ValidationError, TypeError):
            # Preserve poison messages in the configured DLQ after bounded retries.
            logger.error("Invalid payment queue message: id=%s", message.id)
            message.retry()
            continue
        service = delivery(env)
        try:
            delay = await service.consume(payload)
            if delay is None:
                message.ack()
            else:
                message.retry(delaySeconds=delay)
        except Exception as exc:
            # DB unavailable: do not ACK. Queues retries; Outbox remains the recovery source.
            logger.error(
                "Payment queue unavailable: event=%s error=%s", payload.event_id, type(exc).__name__
            )
            message.retry(delaySeconds=service.settings.retry_base)
        finally:
            await service.db.release()
    await safe_relay(env)

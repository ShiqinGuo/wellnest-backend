"""Cloudflare adapters; payment services remain independent of the Worker SDK."""

import logging
from datetime import UTC, datetime

import httpx
from opentelemetry.instrumentation.httpx import AsyncOpenTelemetryTransport
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import ValidationError

from app.domain.queue_message import DeliveryResult, PaymentMessage
from app.payment_settings import load_payment_settings
from app.providers.mock_payment import MockPaymentGateway
from app.providers.worker_http import ServiceBindingTransport
from app.runtime_database import scoped_database
from app.services.payment_delivery import PaymentDelivery
from app.services.payment_workflow import PaymentWorkflow
from app.telemetry import current_headers, extracted_context, message_links, tracer

logger = logging.getLogger(__name__)


class QueuePublisher:
    def __init__(self, binding):
        self.binding = binding

    async def publish(self, message: PaymentMessage) -> None:
        # A JSON string crosses the Python/JS boundary without leaking proxy objects.
        with tracer().start_as_current_span(
            "wellnest-payments publish",
            context=extracted_context(message.headers),
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.system": "cloudflare.queues",
                "messaging.destination.name": "wellnest-payments",
                "messaging.message.id": str(message.event_id),
            },
        ):
            outgoing = message.model_copy(
                update={
                    "headers": {**message.headers, **current_headers()},
                    "published_at": datetime.now(UTC),
                }
            )
            await self.binding.send(outgoing.model_dump_json())


def delivery(env) -> PaymentDelivery:
    settings = load_payment_settings(env)
    db = scoped_database(env)
    gateway = MockPaymentGateway(
        settings,
        AsyncOpenTelemetryTransport(
            ServiceBindingTransport(env.PAYMENT_API, settings.network_timeout)
        ),
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
        logger.error("Outbox relay deferred to recovery: %s", type(exc).__name__, exc_info=True)


async def dispatch(env, path: str, payload: PaymentMessage | None = None) -> DeliveryResult:
    """Fetch placement applies here; Queue and Cron entrypoints never open a DB connection."""
    settings = load_payment_settings(env)
    if settings.internal_key is None:
        raise RuntimeError("Payment internal key is not configured")
    transport = AsyncOpenTelemetryTransport(
        ServiceBindingTransport(env.PAYMENT_API, settings.dispatch_timeout)
    )
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
        with tracer().start_as_current_span(
            "wellnest-payments process",
            context=extracted_context(payload.headers),
            kind=SpanKind.CONSUMER,
            links=message_links(payload.headers),
            attributes={
                "messaging.system": "cloudflare.queues",
                "messaging.destination.name": "wellnest-payments",
                "messaging.message.id": str(payload.event_id),
            },
        ) as span:
            if payload.published_at:
                span.set_attribute(
                    "messaging.delivery.age_ms",
                    max(0, (datetime.now(UTC) - payload.published_at).total_seconds() * 1000),
                )
            try:
                result = await dispatch(env, "consume", payload)
                if result.retry_after is None:
                    message.ack()
                    span.set_attribute("messaging.delivery.action", "ack")
                else:
                    message.retry(delaySeconds=result.retry_after)
                    span.set_attribute("messaging.delivery.action", "retry")
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("messaging.delivery.action", "retry")
                logger.error(
                    "Payment queue unavailable: event=%s error=%s",
                    payload.event_id,
                    type(exc).__name__,
                    exc_info=True,
                )
                message.retry(delaySeconds=settings.retry_base)

"""Outbox owns the retry budget; Queues transports a fenced event reference."""

import asyncio
import logging
from typing import Protocol

from app.domain.payment_states import OutboxStatus
from app.domain.queue_message import PaymentMessage
from app.repositories.outbox import OutboxRepository
from app.services.payment_workflow import PaymentWorkflow

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    async def publish(self, message: PaymentMessage) -> None: ...


class PaymentDelivery:
    def __init__(self, workflow: PaymentWorkflow, publisher: EventPublisher):
        self.workflow = workflow
        self.db = workflow.db
        self.settings = workflow.settings
        self.outbox = OutboxRepository(self.db)
        self.publisher = publisher

    async def relay(self, *, reconcile: bool = False) -> None:
        async with asyncio.timeout(self.settings.relay_timeout):
            if reconcile:
                for _ in range(self.settings.batch_size):
                    if not await self.workflow.schedule_reconciliation():
                        break
            for _ in range(self.settings.batch_size):
                row = await self.outbox.claim(self.settings)
                if row is None:
                    break
                if row["attempts"] > self.settings.max_attempts:
                    await self.outbox.failed(row, "AttemptsExhausted", self.settings)
                    continue
                await self.db.release()
                try:
                    await self.publisher.publish(
                        PaymentMessage(event_id=row["id"], lease_token=row["lease_token"])
                    )
                except Exception as exc:
                    await self.outbox.failed(row, type(exc).__name__, self.settings)
                    logger.warning(
                        "Queue publish failed: event=%s error=%s", row["id"], type(exc).__name__
                    )
                else:
                    await self.outbox.published(row)

    async def consume(self, message: PaymentMessage) -> int | None:
        """Return a queue retry delay; None means safely acknowledge this delivery."""
        row = await self.outbox.get(message.event_id)
        if (
            row is None
            or row["processed_at"] is not None
            or row["status"] == OutboxStatus.failed
            or row["lease_token"] != message.lease_token
        ):
            return None
        # Renew before execution so the recovery relay doesn't republish an active task.
        if not await self.outbox.renew(row, self.settings.lease_seconds):
            return None
        await self.db.release()
        try:
            async with asyncio.timeout(self.settings.execution_timeout):
                await self.workflow.execute(message.event_id)
        except Exception as exc:
            logger.warning(
                "Queue execution failed: event=%s error=%s", message.event_id, type(exc).__name__
            )
            if row["attempts"] >= self.settings.max_attempts:
                await self.outbox.failed(row, type(exc).__name__, self.settings)
                return None
            delay = min(self.settings.retry_cap, self.settings.retry_base ** row["attempts"])
            await self.outbox.retry_execution(row, type(exc).__name__, delay, self.settings)
            return delay
        return None

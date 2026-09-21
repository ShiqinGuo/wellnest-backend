"""DB-driven outbox relay and pending-payment reconciliation; no in-memory timers of record."""

import asyncio
import logging

from app.domain.payment_states import OutboxStatus
from app.payment_tasks import TASK_NAME, celery_app, scoped_database, settings
from app.providers.mock_payment import MockPaymentGateway
from app.repositories.outbox import OutboxRepository
from app.services.payment_workflow import PaymentWorkflow

logger = logging.getLogger(__name__)


def publish(event_id):
    celery_app.send_task(TASK_NAME, args=[str(event_id)], task_id=str(event_id))


async def tick():
    db = scoped_database()
    try:
        workflow = PaymentWorkflow(db, settings, MockPaymentGateway(settings))
        for _ in range(settings.batch_size):
            if not await workflow.schedule_reconciliation():
                break
        outbox = OutboxRepository(db)
        for _ in range(settings.batch_size):
            row = await outbox.claim(settings)
            if row is None:
                break
            if row["attempts"] > settings.max_attempts:
                await outbox.failed(row, "DeliveryOrProcessingAttemptsExhausted", settings)
                logger.error("Outbox exhausted: %s", row["id"])
                continue
            await db.release()
            try:
                await asyncio.to_thread(publish, row["id"])
            except Exception as exc:
                # Exception class only: never log broker credentials or signed URLs.
                await outbox.failed(row, type(exc).__name__, settings)
                if row["status"] == OutboxStatus.failed:
                    logger.error("Outbox failed: %s", row["id"])
            else:
                await outbox.published(row)
    finally:
        await db.release()


async def main():
    while True:
        try:
            await tick()
        except Exception as exc:
            logger.error("Scheduler tick failed: %s", type(exc).__name__)
        await asyncio.sleep(settings.scheduler_interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

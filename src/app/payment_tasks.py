"""Celery entrypoint: celery -A app.payment_tasks:celery_app worker."""

import asyncio
import os
from uuid import UUID

import asyncpg
from celery import Celery
from kombu import Queue

from app.database import ScopedDatabase
from app.payment_settings import payment_settings
from app.providers.mock_payment import MockPaymentGateway
from app.services.payment_workflow import PaymentWorkflow
from app.settings import RUNTIME

TASK_NAME = "wellnest.payment.execute"
QUEUE_NAME = "payments"
settings = payment_settings()
celery_app = Celery("wellnest-payments", broker=settings.broker_url.get_secret_value())
celery_app.conf.update(
    task_queues=(Queue(QUEUE_NAME, durable=True),),
    task_default_queue=QUEUE_NAME,
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_enable_remote_control=False,
    worker_send_task_events=False,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_transport_options={"confirm_publish": True},
    broker_connection_timeout=settings.network_timeout,
    task_publish_retry=False,
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=settings.worker_soft_limit,
    task_time_limit=settings.worker_hard_limit,
)


def scoped_database():
    return ScopedDatabase(
        lambda: asyncpg.connect(
            os.environ["WELLNEST_DATABASE_URL"],
            timeout=RUNTIME.database_timeout_seconds,
            command_timeout=RUNTIME.database_timeout_seconds,
        )
    )


async def execute_event(event_id: str):
    db = scoped_database()
    try:
        workflow = PaymentWorkflow(db, settings, MockPaymentGateway(settings))
        await workflow.execute(UUID(event_id))
    except Exception as exc:
        await db.execute(
            "UPDATE outbox_events SET last_error=$2 WHERE id=$1 AND processed_at IS NULL",
            UUID(event_id),
            type(exc).__name__,
        )
        raise
    finally:
        await db.release()


@celery_app.task(name=TASK_NAME)
def execute(event_id: str):
    # Event remains unprocessed on error; the DB lease/watchdog owns bounded retries.
    asyncio.run(execute_event(event_id))

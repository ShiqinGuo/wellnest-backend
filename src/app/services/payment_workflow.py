import hashlib
from uuid import UUID

from app.database import Database
from app.domain.payment import ChannelCreate, ChannelNotification
from app.domain.payment_states import (
    InboxEvent,
    InboxStateMachine,
    InboxStatus,
    OutboxStatus,
    PaymentStatus,
    PaymentTask,
)
from app.errors import AppError, ErrorCode
from app.payment_settings import PaymentSettings
from app.providers.mock_payment import PaymentGateway
from app.repositories.assessment import AssessmentRepository
from app.repositories.command import CommandRepository
from app.repositories.mock_provider import MockProviderRepository
from app.repositories.outbox import OutboxRepository
from app.repositories.payment import PaymentRepository
from app.repositories.payment_webhook import PaymentWebhookRepository
from app.services.command import CommandService
from app.services.mock_provider import MockProviderService
from app.services.payment import PaymentService


class PaymentWorkflow:
    def __init__(self, db: Database, settings: PaymentSettings, gateway: PaymentGateway):
        self.db = db
        self.settings = settings
        self.gateway = gateway
        self.outbox = OutboxRepository(db)
        self.repository = PaymentRepository(db)
        self.inbox = PaymentWebhookRepository(db)
        self.service = PaymentService(
            self.repository,
            AssessmentRepository(db),
            CommandService(CommandRepository(db)),
            settings,
        )

    async def accept_webhook(self, notification: ChannelNotification) -> None:
        payload = notification.model_dump_json()
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        async with self.db.transaction():
            if await self.repository.get(notification.merchant_payment_id) is None:
                raise AppError(ErrorCode.not_found, "Unknown merchant payment", 404)
            await self.inbox.insert(notification, fingerprint)
            existing = await self.inbox.get(notification.event_id)
            if existing["fingerprint"] != fingerprint:
                raise AppError(ErrorCode.payment_conflict, "Event ID reused with different payload")
            if existing["status"] == InboxStatus.pending:
                await self.outbox.enqueue(PaymentTask.process_webhook, notification.event_id)

    async def execute(self, event_id: UUID) -> None:
        event = await self.outbox.get(event_id)
        if (
            event is None
            or event["processed_at"] is not None
            or event["status"] == OutboxStatus.failed
        ):
            return
        task = PaymentTask(event["task"])
        aggregate_id = event["aggregate_id"]
        if task == PaymentTask.deliver_webhook:
            provider = MockProviderService(MockProviderRepository(self.db), self.settings)
            notification = await provider.notification(aggregate_id)
            await self.db.release()
            await self.gateway.deliver(notification)
            async with self.db.transaction():
                await self.outbox.done(event_id)
            return
        if task == PaymentTask.process_webhook:
            await self.process_webhook(event_id, aggregate_id)
            return
        row = await self.repository.get(aggregate_id)
        if row is None:
            raise ValueError("Missing payment for outbox event")
        if row["status"] != PaymentStatus.pending:
            async with self.db.transaction():
                await self.outbox.done(event_id)
            return
        command = ChannelCreate(
            merchant_payment_id=aggregate_id,
            amount_minor=row["amount_minor"],
            currency=row["currency"],
        )
        await self.db.release()
        # Query by merchant reference survives a create timeout before transaction ID was saved.
        result = await self.gateway.query(aggregate_id) if task == PaymentTask.reconcile else None
        if result is None:
            result = await self.gateway.create(command)
        async with self.db.transaction():
            await self.service.apply_provider_result(aggregate_id, result)
            await self.outbox.done(event_id)

    async def process_webhook(self, event_id: UUID, notification_id: UUID) -> None:
        inbox = await self.inbox.get(notification_id)
        if inbox is None:
            raise ValueError("Missing inbox notification")
        notification = ChannelNotification.model_validate_json(inbox["payload"])
        result = notification
        row = await self.repository.get(inbox["payment_id"])
        if row["status"] not in (PaymentStatus.pending, notification.status):
            await self.db.release()
            result = await self.gateway.query(inbox["payment_id"])
            if result is None:
                raise ValueError("Cannot reconcile conflicting notification")
        async with self.db.transaction():
            current = await self.inbox.get(notification_id, lock=True)
            if current["status"] == InboxStatus.pending:
                outcome, rejection = InboxEvent.accept, None
                try:
                    # All validation occurs before any payment/entitlement writes.
                    await self.service.apply_provider_result(inbox["payment_id"], result)
                except AppError as exc:
                    if exc.code not in (ErrorCode.payment_mismatch, ErrorCode.payment_conflict):
                        raise
                    outcome, rejection = InboxEvent.reject, exc.code.value
                status = InboxStateMachine.transition(InboxStatus.pending, outcome)
                await self.inbox.finish(notification_id, status, rejection)
            await self.outbox.done(event_id)

    async def schedule_reconciliation(self) -> bool:
        async with self.db.transaction():
            row = await self.repository.next_due()
            if row is None:
                return False
            await self.outbox.enqueue(PaymentTask.reconcile, row["id"])
            await self.repository.defer_check(row["id"], self.settings.reconcile_interval)
            return True

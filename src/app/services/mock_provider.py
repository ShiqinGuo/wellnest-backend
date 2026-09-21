import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.payment import ChannelCreate, ChannelNotification, ChannelPayment, CheckoutConfirm
from app.domain.payment_states import PaymentEvent, PaymentStateMachine, PaymentStatus, PaymentTask
from app.errors import AppError, ErrorCode
from app.payment_settings import PaymentSettings
from app.repositories.mock_provider import MockProviderRepository
from app.repositories.outbox import OutboxRepository
from app.settings import RUNTIME


class MockProviderService:
    def __init__(self, repository: MockProviderRepository, settings: PaymentSettings):
        self.repository = repository
        self.settings = settings
        self.outbox = OutboxRepository(repository.conn)

    def view(self, row) -> ChannelPayment:
        return ChannelPayment(
            merchant_payment_id=row["merchant_payment_id"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            transaction_id=row["id"],
            status=row["status"],
            expires_at=row["expires_at"],
            checkout_url=self.settings.public_url + "/api/mock-checkout/" + row["checkout_token"],
        )

    async def expire(self, row):
        if row["status"] == PaymentStatus.pending and row["expires_at"] <= datetime.now(UTC):
            target = PaymentStateMachine.transition(PaymentStatus.pending, PaymentEvent.close)
            row = await self.repository.update(row["id"], target)
            await self.outbox.enqueue(PaymentTask.deliver_webhook, row["id"])
        return row

    async def create(self, command: ChannelCreate) -> ChannelPayment:
        async with self.repository.conn.transaction():
            row = await self.repository.create(
                command,
                uuid4(),
                secrets.token_urlsafe(RUNTIME.token_entropy_bytes),
                uuid4(),
                self.settings.checkout_lifetime,
            )
            if row["amount_minor"] != command.amount_minor or row["currency"] != command.currency:
                raise AppError(ErrorCode.payment_mismatch)
            return self.view(await self.expire(row))

    async def query(self, payment_id: UUID) -> ChannelPayment:
        async with self.repository.conn.transaction():
            row = await self.repository.by_merchant(payment_id)
            if row is None:
                raise AppError(ErrorCode.not_found)
            return self.view(await self.expire(row))

    async def checkout(self, token: str, command: CheckoutConfirm | None = None) -> ChannelPayment:
        async with self.repository.conn.transaction():
            row = await self.repository.by_token(token)
            if row is None:
                raise AppError(ErrorCode.not_found)
            row = await self.expire(row)
            if command and row["status"] != PaymentStatus.closed:
                event = (
                    PaymentEvent.succeed
                    if command.outcome == PaymentStatus.succeeded
                    else PaymentEvent.fail
                )
                target = PaymentStateMachine.transition(PaymentStatus(row["status"]), event)
                row = await self.repository.update(row["id"], target)
                await self.outbox.enqueue(PaymentTask.deliver_webhook, row["id"])
            return self.view(row)

    async def notification(self, transaction_id: UUID) -> ChannelNotification:
        row = await self.repository.by_id(transaction_id)
        if row is None or row["status"] == PaymentStatus.pending:
            raise ValueError("No terminal channel outcome")
        return ChannelNotification(**self.view(row).model_dump(), event_id=row["event_id"])

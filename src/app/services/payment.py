from uuid import UUID

from app.domain.enums import SubscriptionEvent, SubscriptionStatus
from app.domain.payment import ChannelPayment, PayCommand, PaymentData
from app.domain.payment_states import (
    PaymentEvent,
    PaymentStateMachine,
    PaymentStatus,
    PaymentTask,
)
from app.domain.state_machine import SubscriptionStateMachine
from app.errors import AppError, ErrorCode
from app.payment_settings import PaymentSettings
from app.repositories.assessment import AssessmentRepository
from app.repositories.command import CommandRepository
from app.repositories.outbox import OutboxRepository
from app.repositories.payment import PaymentRepository
from app.services.command import CommandService


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepository,
        assessments: AssessmentRepository,
        commands: CommandService,
        settings: PaymentSettings,
        outbox: OutboxRepository,
        locks: CommandRepository,
    ):
        self.repository = repository
        self.assessments = assessments
        self.commands = commands
        self.settings = settings
        self.outbox = outbox
        self.locks = locks

    async def create(self, user_id: UUID, key: str, command: PayCommand) -> PaymentData:
        async def operation() -> PaymentData:
            if not await self.assessments.has_completed(user_id):
                raise AppError(ErrorCode.assessment_required)
            if await self.repository.is_member(user_id):
                raise AppError(ErrorCode.already_subscribed)
            row = await self.repository.pending(user_id, command.plan_id)
            if row is None:
                row = await self.repository.create(
                    user_id,
                    command.plan_id,
                    self.settings.amount_minor,
                    self.settings.currency,
                    self.settings.reconcile_interval,
                )
                await self.outbox.enqueue(PaymentTask.create, row.id)
            return self.repository.data(row)

        return await self.commands.run(
            user_id, "payment.create", key, command, operation, PaymentData
        )

    async def get(self, user_id: UUID, payment_id: UUID) -> PaymentData:
        row = await self.repository.get(payment_id, user_id)
        if row is None:
            raise AppError(ErrorCode.not_found)
        return self.repository.data(row)

    async def refresh(self, user_id: UUID, payment_id: UUID) -> None:
        async with self.repository.conn.transaction():
            row = await self.repository.get(payment_id, user_id, lock=True)
            if row is None:
                raise AppError(ErrorCode.not_found)
            scheduled = await self.repository.schedule_refresh(
                payment_id, self.settings.refresh_interval
            )
            if scheduled:
                await self.outbox.enqueue(PaymentTask.reconcile, payment_id)

    async def apply_provider_result(self, payment_id: UUID, result: ChannelPayment) -> None:
        """Caller owns the transaction, including inbox/outbox completion."""
        identity = await self.repository.get(payment_id)
        if identity is None:
            raise AppError(ErrorCode.not_found)
        # Consistent lock ordering: user first, then payment; create uses the same user lock.
        await self.locks.lock_user(identity.user_id)
        row = await self.repository.get(payment_id, lock=True)
        if row is None:
            raise AppError(ErrorCode.not_found)
        if (
            result.merchant_payment_id != payment_id
            or result.amount_minor != row.amount_minor
            or result.currency != row.currency
            or (
                row.provider_transaction_id is not None
                and row.provider_transaction_id != result.transaction_id
            )
        ):
            raise AppError(ErrorCode.payment_mismatch)
        current = PaymentStatus(row.status)
        if result.status == PaymentStatus.pending:
            target = current  # An old pending observation cannot regress a terminal payment.
        else:
            event = {
                PaymentStatus.succeeded: PaymentEvent.succeed,
                PaymentStatus.failed: PaymentEvent.fail,
                PaymentStatus.closed: PaymentEvent.close,
            }[result.status]
            target = PaymentStateMachine.transition(current, event)
        await self.repository.apply_channel(payment_id, result, target)
        if target == PaymentStatus.succeeded:
            state = (
                SubscriptionStatus.active
                if await self.repository.is_member(row.user_id)
                else SubscriptionStatus.inactive
            )
            SubscriptionStateMachine.transition(state, SubscriptionEvent.activate)
            await self.repository.activate(row.user_id, row.plan_id, payment_id)

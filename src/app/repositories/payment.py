from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import Database
from app.domain.payment import ChannelPayment, PaymentData
from app.domain.payment_states import Currency, PaymentProvider, PaymentStatus
from app.models import Payment, Subscription
from app.repositories.rows import PAYMENT_ROW, PaymentRow, optional_row, required_row


class PaymentRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def is_member(self, user_id: UUID) -> bool:
        return await self.conn.fetchval(select(exists().where(Subscription.user_id == user_id)))

    async def get(
        self, payment_id: UUID, user_id: UUID | None = None, *, lock: bool = False
    ) -> PaymentRow | None:
        query = select(Payment).where(Payment.id == payment_id)
        if user_id is not None:
            query = query.where(Payment.user_id == user_id)
        if lock:
            query = query.with_for_update()
        return optional_row(await self.conn.fetchrow(query), PAYMENT_ROW)

    async def pending(self, user_id: UUID, plan_id: str) -> PaymentRow | None:
        return optional_row(
            await self.conn.fetchrow(
                select(Payment).where(
                    Payment.user_id == user_id,
                    Payment.plan_id == plan_id,
                    Payment.status == PaymentStatus.pending,
                )
            ),
            PAYMENT_ROW,
        )

    @staticmethod
    def data(row: PaymentRow) -> PaymentData:
        return PaymentData.model_validate(asdict(row))

    async def create(
        self,
        user_id: UUID,
        plan_id: str,
        amount_minor: int,
        currency: Currency,
        check_interval: int,
    ) -> PaymentRow:
        return required_row(
            await self.conn.fetchrow(
                insert(Payment)
                .values(
                    id=uuid4(),
                    user_id=user_id,
                    plan_id=plan_id,
                    status=PaymentStatus.pending,
                    amount_minor=amount_minor,
                    currency=currency,
                    provider=PaymentProvider.mock,
                    next_check_at=func.now() + timedelta(seconds=check_interval),
                )
                .returning(Payment)
            ),
            PAYMENT_ROW,
        )

    async def schedule_refresh(self, payment_id: UUID, interval: int) -> bool:
        return (
            await self.conn.fetchval(
                update(Payment)
                .where(
                    Payment.id == payment_id,
                    Payment.status == PaymentStatus.pending,
                    or_(
                        Payment.last_refresh_at.is_(None),
                        Payment.last_refresh_at < func.now() - timedelta(seconds=interval),
                    ),
                )
                .values(last_refresh_at=func.now())
                .returning(Payment.id)
            )
            is not None
        )

    async def apply_channel(
        self, payment_id: UUID, result: ChannelPayment, status: PaymentStatus
    ) -> None:
        await self.conn.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(
                provider_transaction_id=result.transaction_id,
                checkout_url=result.checkout_url,
                status=status,
                updated_at=func.now(),
            )
        )

    async def activate(self, user_id: UUID, plan_id: str, payment_id: UUID) -> None:
        await self.conn.execute(
            insert(Subscription)
            .values(user_id=user_id, plan_id=plan_id, source_payment_id=payment_id)
            .on_conflict_do_nothing(index_elements=[Subscription.user_id])
        )

    async def next_due(self) -> UUID | None:
        return await self.conn.fetchval(
            select(Payment.id)
            .where(Payment.status == PaymentStatus.pending, Payment.next_check_at <= func.now())
            .order_by(Payment.next_check_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    async def defer_check(self, payment_id: UUID, interval: int) -> None:
        await self.conn.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(next_check_at=func.now() + timedelta(seconds=interval))
        )

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import Database
from app.domain.payment import ChannelCreate
from app.domain.payment_states import PaymentStatus
from app.models import MockProviderPayment
from app.repositories.rows import PROVIDER_ROW, ProviderRow, optional_row, required_row


class MockProviderRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def create(
        self,
        command: ChannelCreate,
        transaction_id: UUID,
        token: str,
        event_id: UUID,
        lifetime: int,
    ) -> ProviderRow:
        await self.conn.execute(
            insert(MockProviderPayment)
            .values(
                id=transaction_id,
                merchant_payment_id=command.merchant_payment_id,
                amount_minor=command.amount_minor,
                currency=command.currency,
                status=PaymentStatus.pending,
                checkout_token=token,
                event_id=event_id,
                expires_at=func.now() + timedelta(seconds=lifetime),
            )
            .on_conflict_do_nothing(index_elements=[MockProviderPayment.merchant_payment_id])
        )
        row = await self.by_merchant(command.merchant_payment_id)
        if row is None:
            raise LookupError("Created provider payment is missing")
        return row

    async def by_merchant(self, payment_id: UUID) -> ProviderRow | None:
        return optional_row(
            await self.conn.fetchrow(
                select(MockProviderPayment)
                .where(MockProviderPayment.merchant_payment_id == payment_id)
                .with_for_update()
            ),
            PROVIDER_ROW,
        )

    async def by_token(self, token: str) -> ProviderRow | None:
        return optional_row(
            await self.conn.fetchrow(
                select(MockProviderPayment)
                .where(MockProviderPayment.checkout_token == token)
                .with_for_update()
            ),
            PROVIDER_ROW,
        )

    async def by_id(self, transaction_id: UUID) -> ProviderRow | None:
        return optional_row(
            await self.conn.fetchrow(
                select(MockProviderPayment).where(MockProviderPayment.id == transaction_id)
            ),
            PROVIDER_ROW,
        )

    async def update(self, transaction_id: UUID, status: PaymentStatus) -> ProviderRow:
        return required_row(
            await self.conn.fetchrow(
                update(MockProviderPayment)
                .where(MockProviderPayment.id == transaction_id)
                .values(status=status, updated_at=func.now())
                .returning(MockProviderPayment)
            ),
            PROVIDER_ROW,
        )

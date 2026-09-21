from uuid import UUID

from app.database import Database
from app.domain.payment import ChannelCreate
from app.domain.payment_states import PaymentStatus


class MockProviderRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def create(self, command: ChannelCreate, transaction_id, token, event_id, lifetime):
        await self.conn.execute(
            """INSERT INTO mock_provider_payments
            (id,merchant_payment_id,amount_minor,currency,status,checkout_token,event_id,expires_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,now()+$8*interval '1 second')
            ON CONFLICT(merchant_payment_id) DO NOTHING""",
            transaction_id,
            command.merchant_payment_id,
            command.amount_minor,
            command.currency,
            PaymentStatus.pending,
            token,
            event_id,
            lifetime,
        )
        return await self.by_merchant(command.merchant_payment_id)

    async def by_merchant(self, payment_id: UUID):
        return await self.conn.fetchrow(
            "SELECT * FROM mock_provider_payments WHERE merchant_payment_id=$1 FOR UPDATE",
            payment_id,
        )

    async def by_token(self, token: str):
        return await self.conn.fetchrow(
            "SELECT * FROM mock_provider_payments WHERE checkout_token=$1 FOR UPDATE",
            token,
        )

    async def by_id(self, transaction_id: UUID):
        return await self.conn.fetchrow(
            "SELECT * FROM mock_provider_payments WHERE id=$1",
            transaction_id,
        )

    async def update(self, transaction_id: UUID, status: PaymentStatus):
        return await self.conn.fetchrow(
            "UPDATE mock_provider_payments SET status=$2,updated_at=now() WHERE id=$1 RETURNING *",
            transaction_id,
            status,
        )

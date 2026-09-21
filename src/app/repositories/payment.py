from uuid import UUID, uuid4

from app.database import Database
from app.domain.payment import ChannelPayment, PaymentData
from app.domain.payment_states import Currency, PaymentProvider, PaymentStatus


class PaymentRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def is_member(self, user_id: UUID) -> bool:
        return await self.conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM subscriptions WHERE user_id=$1)",
            user_id,
        )

    async def get(self, payment_id: UUID, user_id: UUID | None = None, *, lock=False):
        row = await self.conn.fetchrow(
            "SELECT * FROM payments WHERE id=$1 AND ($2::uuid IS NULL OR user_id=$2)"
            + (" FOR UPDATE" if lock else ""),
            payment_id,
            user_id,
        )
        return row

    async def pending(self, user_id: UUID, plan_id: str):
        return await self.conn.fetchrow(
            "SELECT * FROM payments WHERE user_id=$1 AND plan_id=$2 AND status=$3",
            user_id,
            plan_id,
            PaymentStatus.pending,
        )

    @staticmethod
    def data(row) -> PaymentData:
        return PaymentData.model_validate(dict(row))

    async def create(
        self,
        user_id: UUID,
        plan_id: str,
        amount_minor: int,
        currency: Currency,
        check_interval: int,
    ):
        return await self.conn.fetchrow(
            """INSERT INTO payments
            (id,user_id,plan_id,status,amount_minor,currency,provider,next_check_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,now()+$8*interval '1 second') RETURNING *""",
            uuid4(),
            user_id,
            plan_id,
            PaymentStatus.pending,
            amount_minor,
            currency,
            PaymentProvider.mock,
            check_interval,
        )

    async def schedule_refresh(self, payment_id: UUID, interval: int) -> bool:
        return (
            await self.conn.fetchval(
                """UPDATE payments SET last_refresh_at=now() WHERE id=$1 AND status=$2
            AND (last_refresh_at IS NULL OR last_refresh_at<now()-$3*interval '1 second')
            RETURNING id""",
                payment_id,
                PaymentStatus.pending,
                interval,
            )
            is not None
        )

    async def apply_channel(self, payment_id: UUID, result: ChannelPayment, status: PaymentStatus):
        await self.conn.execute(
            """UPDATE payments SET provider_transaction_id=$2,checkout_url=$3,status=$4,
            updated_at=now() WHERE id=$1""",
            payment_id,
            result.transaction_id,
            result.checkout_url,
            status,
        )

    async def activate(self, user_id: UUID, plan_id: str, payment_id: UUID):
        await self.conn.execute(
            """INSERT INTO subscriptions(user_id,plan_id,source_payment_id)
            VALUES($1,$2,$3) ON CONFLICT(user_id) DO NOTHING""",
            user_id,
            plan_id,
            payment_id,
        )

    async def next_due(self):
        return await self.conn.fetchrow(
            """SELECT id FROM payments WHERE status=$1 AND next_check_at<=now()
            ORDER BY next_check_at FOR UPDATE SKIP LOCKED LIMIT 1""",
            PaymentStatus.pending,
        )

    async def defer_check(self, payment_id: UUID, interval: int):
        await self.conn.execute(
            "UPDATE payments SET next_check_at=now()+$2*interval '1 second' WHERE id=$1",
            payment_id,
            interval,
        )

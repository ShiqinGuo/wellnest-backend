from uuid import UUID

from app.database import Database
from app.domain.payment import ChannelNotification
from app.domain.payment_states import InboxStatus


class PaymentWebhookRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def insert(self, notification: ChannelNotification, fingerprint: str):
        await self.conn.execute(
            """INSERT INTO payment_webhook_inbox(id,payment_id,status,payload,fingerprint)
            VALUES($1,$2,$3,$4::jsonb,$5) ON CONFLICT(id) DO NOTHING""",
            notification.event_id,
            notification.merchant_payment_id,
            InboxStatus.pending,
            notification.model_dump_json(),
            fingerprint,
        )

    async def get(self, event_id: UUID, *, lock: bool = False):
        return await self.conn.fetchrow(
            "SELECT * FROM payment_webhook_inbox WHERE id=$1" + (" FOR UPDATE" if lock else ""),
            event_id,
        )

    async def finish(self, event_id: UUID, status: InboxStatus, rejection: str | None):
        await self.conn.execute(
            "UPDATE payment_webhook_inbox SET status=$2,rejection_code=$3 WHERE id=$1",
            event_id,
            status,
            rejection,
        )

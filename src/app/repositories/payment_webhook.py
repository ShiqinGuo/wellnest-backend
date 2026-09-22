from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import Database
from app.domain.payment import ChannelNotification
from app.domain.payment_states import InboxStatus
from app.models import PaymentWebhook
from app.repositories.rows import WEBHOOK_ROW, WebhookRow, optional_row


class PaymentWebhookRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def insert(self, notification: ChannelNotification, fingerprint: str) -> None:
        await self.conn.execute(
            insert(PaymentWebhook)
            .values(
                id=notification.event_id,
                payment_id=notification.merchant_payment_id,
                status=InboxStatus.pending,
                payload=notification.model_dump(mode="json"),
                fingerprint=fingerprint,
            )
            .on_conflict_do_nothing(index_elements=[PaymentWebhook.id])
        )

    async def get(self, event_id: UUID, *, lock: bool = False) -> WebhookRow | None:
        query = select(PaymentWebhook).where(PaymentWebhook.id == event_id)
        if lock:
            query = query.with_for_update()
        return optional_row(await self.conn.fetchrow(query), WEBHOOK_ROW)

    async def finish(self, event_id: UUID, status: InboxStatus, rejection: str | None) -> None:
        await self.conn.execute(
            update(PaymentWebhook)
            .where(PaymentWebhook.id == event_id)
            .values(status=status, rejection_code=rejection)
        )

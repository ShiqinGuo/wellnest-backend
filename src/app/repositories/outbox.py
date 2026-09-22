from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.database import Database
from app.domain.payment_states import OutboxEvent, OutboxStateMachine, OutboxStatus, PaymentTask
from app.models import Outbox
from app.payment_settings import PaymentSettings
from app.repositories.rows import OUTBOX_ROW, OutboxRow, optional_row
from app.telemetry import current_headers


class OutboxRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def enqueue(self, task: PaymentTask, aggregate_id: UUID) -> None:
        await self.conn.execute(
            insert(Outbox)
            .values(
                id=uuid4(),
                task=task,
                aggregate_id=aggregate_id,
                status=OutboxStatus.pending,
                available_at=func.now(),
                headers=current_headers(),
            )
            .on_conflict_do_nothing()
        )

    async def claim(self, settings: PaymentSettings) -> OutboxRow | None:
        candidate = (
            select(Outbox.id)
            .where(
                Outbox.processed_at.is_(None),
                Outbox.status != OutboxStatus.failed,
                Outbox.available_at <= func.now(),
                or_(Outbox.lease_until.is_(None), Outbox.lease_until <= func.now()),
            )
            .order_by(Outbox.available_at, Outbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        return optional_row(
            await self.conn.fetchrow(
                update(Outbox)
                .where(Outbox.id == candidate.scalar_subquery())
                .values(
                    lease_token=uuid4(),
                    lease_until=func.now() + timedelta(seconds=settings.lease_seconds),
                    attempts=Outbox.attempts + 1,
                )
                .returning(Outbox)
            ),
            OUTBOX_ROW,
        )

    async def published(self, row: OutboxRow) -> None:
        status = OutboxStateMachine.transition(row.status, OutboxEvent.publish)
        await self.conn.execute(
            update(Outbox)
            .where(
                Outbox.id == row.id,
                Outbox.lease_token == row.lease_token,
                Outbox.processed_at.is_(None),
                Outbox.status != OutboxStatus.failed,
            )
            .values(status=status)
        )

    async def failed(self, row: OutboxRow, error: str, settings: PaymentSettings) -> None:
        event = OutboxEvent.exhaust if row.attempts >= settings.max_attempts else OutboxEvent.retry
        status = OutboxStateMachine.transition(row.status, event)
        delay = min(
            settings.retry_cap, settings.retry_base ** min(row.attempts, settings.max_attempts)
        )
        await self.conn.execute(
            update(Outbox)
            .where(
                Outbox.id == row.id,
                Outbox.lease_token == row.lease_token,
                Outbox.processed_at.is_(None),
            )
            .values(
                status=status,
                lease_token=None,
                lease_until=None,
                last_error=error[:128],
                available_at=func.now() + timedelta(seconds=delay),
            )
        )

    async def get(self, event_id: UUID) -> OutboxRow | None:
        return optional_row(
            await self.conn.fetchrow(select(Outbox).where(Outbox.id == event_id)), OUTBOX_ROW
        )

    async def renew(self, row: OutboxRow, lease_seconds: int) -> bool:
        return (
            await self.conn.fetchval(
                update(Outbox)
                .where(
                    Outbox.id == row.id,
                    Outbox.lease_token == row.lease_token,
                    Outbox.processed_at.is_(None),
                    Outbox.status != OutboxStatus.failed,
                )
                .values(lease_until=func.now() + timedelta(seconds=lease_seconds))
                .returning(Outbox.id)
            )
            is not None
        )

    async def retry_execution(
        self, row: OutboxRow, error: str, delay: int, settings: PaymentSettings
    ) -> None:
        await self.conn.execute(
            update(Outbox)
            .where(
                Outbox.id == row.id,
                Outbox.lease_token == row.lease_token,
                Outbox.processed_at.is_(None),
                Outbox.status != OutboxStatus.failed,
            )
            .values(
                attempts=Outbox.attempts + 1,
                last_error=error[:128],
                lease_until=func.now() + timedelta(seconds=delay + settings.lease_seconds),
            )
        )

    async def done(self, event_id: UUID) -> None:
        await self.conn.execute(
            update(Outbox)
            .where(Outbox.id == event_id)
            .values(processed_at=func.now(), last_error=None)
        )

    async def requeue(self, event_id: UUID) -> bool:
        status = OutboxStateMachine.transition(OutboxStatus.failed, OutboxEvent.requeue)
        other = aliased(Outbox)
        open_task = exists().where(
            other.task == Outbox.task,
            other.aggregate_id == Outbox.aggregate_id,
            other.id != event_id,
            other.status != OutboxStatus.failed,
            other.processed_at.is_(None),
        )
        return (
            await self.conn.fetchval(
                update(Outbox)
                .where(
                    Outbox.id == event_id,
                    Outbox.status == OutboxStatus.failed,
                    Outbox.processed_at.is_(None),
                    ~open_task,
                )
                .values(
                    status=status,
                    attempts=0,
                    lease_until=None,
                    lease_token=None,
                    available_at=func.now(),
                    last_error=None,
                )
                .returning(Outbox.id)
            )
            is not None
        )

import json
from uuid import UUID, uuid4

from app.database import Database
from app.domain.payment_states import OutboxEvent, OutboxStateMachine, OutboxStatus, PaymentTask
from app.payment_settings import PaymentSettings
from app.telemetry import current_headers


class OutboxRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def enqueue(self, task: PaymentTask, aggregate_id: UUID) -> None:
        await self.conn.execute(
            """INSERT INTO outbox_events(id,task,aggregate_id,status,available_at,headers)
            VALUES($1,$2,$3,$4,now(),$5::jsonb) ON CONFLICT DO NOTHING""",
            uuid4(),
            task,
            aggregate_id,
            OutboxStatus.pending,
            json.dumps(current_headers()),
        )

    async def claim(self, settings: PaymentSettings):
        return await self.conn.fetchrow(
            """UPDATE outbox_events SET lease_token=$1,
            lease_until=now()+$2*interval '1 second', attempts=attempts+1
            WHERE id=(SELECT id FROM outbox_events WHERE processed_at IS NULL
              AND status<>$3 AND available_at<=now()
              AND (lease_until IS NULL OR lease_until<=now())
              ORDER BY available_at,created_at FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING *""",
            uuid4(),
            settings.lease_seconds,
            OutboxStatus.failed,
        )

    async def published(self, row) -> None:
        status = OutboxStateMachine.transition(OutboxStatus(row["status"]), OutboxEvent.publish)
        await self.conn.execute(
            "UPDATE outbox_events SET status=$3 WHERE id=$1 AND lease_token=$2 "
            "AND processed_at IS NULL AND status<>$4",
            row["id"],
            row["lease_token"],
            status,
            OutboxStatus.failed,
        )

    async def failed(self, row, error: str, settings: PaymentSettings) -> None:
        event = (
            OutboxEvent.exhaust if row["attempts"] >= settings.max_attempts else OutboxEvent.retry
        )
        status = OutboxStateMachine.transition(OutboxStatus(row["status"]), event)
        delay = min(
            settings.retry_cap, settings.retry_base ** min(row["attempts"], settings.max_attempts)
        )
        await self.conn.execute(
            """UPDATE outbox_events SET status=$3,lease_token=NULL,lease_until=NULL,
            last_error=$4,available_at=now()+$5*interval '1 second'
            WHERE id=$1 AND lease_token=$2 AND processed_at IS NULL""",
            row["id"],
            row["lease_token"],
            status,
            error[:128],
            delay,
        )

    async def get(self, event_id: UUID):
        return await self.conn.fetchrow("SELECT * FROM outbox_events WHERE id=$1", event_id)

    async def renew(self, row, lease_seconds: int) -> bool:
        return (
            await self.conn.fetchval(
                """UPDATE outbox_events SET lease_until=now()+$3*interval '1 second'
            WHERE id=$1 AND lease_token=$2 AND processed_at IS NULL AND status<>$4
            RETURNING id""",
                row["id"],
                row["lease_token"],
                lease_seconds,
                OutboxStatus.failed,
            )
            is not None
        )

    async def retry_execution(self, row, error: str, delay: int, settings: PaymentSettings):
        await self.conn.execute(
            """UPDATE outbox_events SET attempts=attempts+1,last_error=$3,
            lease_until=now()+$4*interval '1 second'
            WHERE id=$1 AND lease_token=$2 AND processed_at IS NULL AND status<>$5""",
            row["id"],
            row["lease_token"],
            error[:128],
            delay + settings.lease_seconds,
            OutboxStatus.failed,
        )

    async def done(self, event_id: UUID) -> None:
        await self.conn.execute(
            "UPDATE outbox_events SET processed_at=now(),last_error=NULL WHERE id=$1",
            event_id,
        )

    async def requeue(self, event_id: UUID) -> bool:
        status = OutboxStateMachine.transition(OutboxStatus.failed, OutboxEvent.requeue)
        return (
            await self.conn.fetchval(
                """UPDATE outbox_events SET status=$2,attempts=0,lease_until=NULL,
            lease_token=NULL,available_at=now(),last_error=NULL
            WHERE id=$1 AND status=$3 AND processed_at IS NULL
            AND NOT EXISTS(SELECT 1 FROM outbox_events other WHERE other.task=outbox_events.task
                AND other.aggregate_id=outbox_events.aggregate_id AND other.id<>$1
                AND other.status<>$3 AND other.processed_at IS NULL) RETURNING id""",
                event_id,
                status,
                OutboxStatus.failed,
            )
            is not None
        )

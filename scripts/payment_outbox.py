"""Container-local operator command: list failed events or explicitly requeue one."""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import func, select

from app.domain.payment_states import OutboxStatus
from app.models import Outbox
from app.repositories.outbox import OutboxRepository
from app.runtime_database import scoped_database


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requeue", type=UUID)
    args = parser.parse_args()
    db = scoped_database()
    try:
        if args.requeue:
            print(
                "requeued" if await OutboxRepository(db).requeue(args.requeue) else "not requeued"
            )
        else:
            failed = (
                select(
                    Outbox.id, Outbox.task, Outbox.aggregate_id, Outbox.attempts, Outbox.last_error
                )
                .where(Outbox.status == OutboxStatus.failed, Outbox.processed_at.is_(None))
                .order_by(Outbox.created_at)
                .limit(100)
                .subquery()
            )
            value = await db.fetchval(select(func.json_agg(failed.table_valued())))
            print(value)
    finally:
        await db.release()


if __name__ == "__main__":
    asyncio.run(main())

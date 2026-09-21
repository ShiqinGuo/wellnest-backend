"""Container-local operator command: list failed events or explicitly requeue one."""

import argparse
import asyncio
from uuid import UUID

from app.payment_tasks import scoped_database
from app.repositories.outbox import OutboxRepository


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
            value = await db.fetchval(
                """SELECT coalesce(json_agg(t),'[]') FROM
                (SELECT id,task,aggregate_id,attempts,last_error FROM outbox_events
                 WHERE status='failed' AND processed_at IS NULL ORDER BY created_at LIMIT 100) t"""
            )
            print(value)
    finally:
        await db.release()


if __name__ == "__main__":
    asyncio.run(main())

import os
from collections.abc import AsyncIterator
from typing import Annotated

import asyncpg
from fastapi import Depends, Request

from app.database import Database, ScopedDatabase
from app.settings import RUNTIME


async def connect(request: Request) -> asyncpg.Connection:
    env = request.scope.get("env")
    if env is not None:
        hd = env.HYPERDRIVE
        conn = await asyncpg.connect(
            host=hd.host,
            port=int(hd.port),
            user=hd.user,
            password=hd.password,
            database=hd.database,
            ssl=False,
            statement_cache_size=0,
            timeout=RUNTIME.database_timeout_seconds,
            command_timeout=RUNTIME.database_timeout_seconds,
        )
    else:
        conn = await asyncpg.connect(
            os.environ["WELLNEST_DATABASE_URL"],
            timeout=RUNTIME.database_timeout_seconds,
            command_timeout=RUNTIME.database_timeout_seconds,
        )
    return conn


async def connection(request: Request) -> AsyncIterator[Database]:
    db = ScopedDatabase(lambda: connect(request))
    try:
        yield db
    finally:
        await db.release()


DatabaseDep = Annotated[Database, Depends(connection)]

"""Connections are scoped to one HTTP request, queue delivery or scheduled invocation."""

import os

import asyncpg

from app.database import ScopedDatabase
from app.settings import RUNTIME


async def connect(env=None) -> asyncpg.Connection:
    options = {
        "timeout": RUNTIME.database_timeout_seconds,
        "command_timeout": RUNTIME.database_timeout_seconds,
    }
    if env is not None:
        hd = env.HYPERDRIVE
        return await asyncpg.connect(
            host=hd.host,
            port=int(hd.port),
            user=hd.user,
            password=hd.password,
            database=hd.database,
            ssl=False,
            statement_cache_size=0,
            **options,
        )
    return await asyncpg.connect(os.environ["WELLNEST_DATABASE_URL"], **options)


def scoped_database(env=None) -> ScopedDatabase:
    return ScopedDatabase(lambda: connect(env))

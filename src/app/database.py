from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol

import asyncpg


class Database(Protocol):
    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None: ...
    async def fetchval(self, query: str, *args: object) -> object: ...
    async def execute(self, query: str, *args: object) -> str: ...
    def transaction(self): ...
    async def release(self) -> None: ...


class ScopedDatabase:
    """One connection per database phase, released before inference and at request end.

    Request-scoped and sequential by design. External inference holds no connection.
    Hyperdrive pools physical connections in the Worker environment.
    """

    def __init__(self, connect: Callable[[], Awaitable[asyncpg.Connection]]):
        self.connect = connect
        self.active: asyncpg.Connection | None = None
        self.cached: asyncpg.Connection | None = None

    @asynccontextmanager
    async def acquired(self) -> AsyncIterator[asyncpg.Connection]:
        if self.active is not None:
            yield self.active
            return
        if self.cached is None:
            self.cached = await self.connect()
        yield self.cached

    async def release(self) -> None:
        if self.active is not None:
            raise RuntimeError("Cannot release an active transaction")
        if self.cached is not None:
            conn, self.cached = self.cached, None
            await conn.close()

    @asynccontextmanager
    async def transaction(self):
        if self.active is not None:
            raise RuntimeError("Nested service transaction is not supported")
        async with self.acquired() as conn:
            self.active = conn
            try:
                async with conn.transaction():
                    yield
            finally:
                self.active = None

    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None:
        async with self.acquired() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: object) -> object:
        async with self.acquired() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args: object) -> str:
        async with self.acquired() as conn:
            return await conn.execute(query, *args)

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

import asyncpg
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.sql import Select
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.dml import Delete, Insert, Update

from app.log_events import committed_events

type Statement = Select | Insert | Update | Delete


class Database(Protocol):
    async def fetchrow(self, statement: Statement) -> asyncpg.Record | None: ...
    async def fetchval(self, statement: Statement) -> Any: ...
    async def execute(self, statement: Statement) -> str: ...
    def transaction(self) -> AbstractAsyncContextManager[None]: ...
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
    async def transaction(self) -> AsyncIterator[None]:
        if self.active is not None:
            raise RuntimeError("Nested service transaction is not supported")
        async with self.acquired() as conn:
            self.active = conn
            try:
                with committed_events():
                    async with conn.transaction():
                        yield
            finally:
                self.active = None

    async def fetchrow(self, statement: Statement) -> asyncpg.Record | None:
        async with self.acquired() as conn:
            query, args = compile_statement(statement)
            return await conn.fetchrow(query, *args)

    async def fetchval(self, statement: Statement) -> Any:
        async with self.acquired() as conn:
            query, args = compile_statement(statement)
            return await conn.fetchval(query, *args)

    async def execute(self, statement: Statement) -> str:
        async with self.acquired() as conn:
            query, args = compile_statement(statement)
            return await conn.execute(query, *args)


DIALECT = PGDialect_asyncpg()


def compile_statement(statement: Statement) -> tuple[str, tuple[object, ...]]:
    """Compile bound expressions without greenlet; SQL strings are not an accepted API."""
    if not isinstance(statement, (Select, Insert, Update, Delete)):
        raise TypeError("Database operations require a SQLAlchemy expression")
    compiled = statement.compile(dialect=DIALECT)
    if not isinstance(compiled, SQLCompiler):
        raise TypeError("Expected an executable SQL expression")
    expanded = compiled.construct_expanded_state()
    processors = {
        name: bind.type.dialect_impl(DIALECT).bind_processor(DIALECT)
        for name, bind in compiled.binds.items()
    }
    processors.update(expanded.processors)
    values = tuple(
        processor(expanded.parameters[name])
        if (processor := processors.get(name)) is not None
        else expanded.parameters[name]
        for name in expanded.positiontup or ()
    )
    return expanded.statement, values

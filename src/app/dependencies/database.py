from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from app.database import Database
from app.runtime_database import scoped_database


async def connection(request: Request) -> AsyncIterator[Database]:
    db = scoped_database(request.scope.get("env"))
    try:
        yield db
    finally:
        await db.release()


DatabaseDep = Annotated[Database, Depends(connection)]

from contextlib import AbstractAsyncContextManager
from datetime import datetime

from sqlalchemy import func, insert, select

from app.database import Database
from app.domain.session import IdentityData
from app.models import AuthSession, User


class SessionRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self.conn.transaction()

    async def find(self, token_hash: str) -> IdentityData | None:
        row = await self.conn.fetchrow(
            select(AuthSession.id, AuthSession.user_id).where(
                AuthSession.token_hash == token_hash, AuthSession.expires_at > func.now()
            )
        )
        return IdentityData(session_id=row["id"], user_id=row["user_id"]) if row else None

    async def create(self, identity: IdentityData, token_hash: str, expires_at: datetime) -> None:
        await self.conn.execute(insert(User).values(id=identity.user_id))
        await self.conn.execute(
            insert(AuthSession).values(
                id=identity.session_id,
                user_id=identity.user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )

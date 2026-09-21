from datetime import datetime

from app.database import Database
from app.domain.session import IdentityData


class SessionRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    def transaction(self):
        return self.conn.transaction()

    async def find(self, token_hash: str) -> IdentityData | None:
        row = await self.conn.fetchrow(
            "SELECT id,user_id FROM auth_sessions WHERE token_hash=$1 AND expires_at>now()",
            token_hash,
        )
        return IdentityData(session_id=row["id"], user_id=row["user_id"]) if row else None

    async def create(self, identity: IdentityData, token_hash: str, expires_at: datetime) -> None:
        await self.conn.execute("INSERT INTO users(id) VALUES($1)", identity.user_id)
        await self.conn.execute(
            "INSERT INTO auth_sessions(id,user_id,token_hash,expires_at) VALUES($1,$2,$3,$4)",
            identity.session_id,
            identity.user_id,
            token_hash,
            expires_at,
        )

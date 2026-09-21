from app.database import Database


class HealthRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def check_database(self) -> None:
        await self.conn.fetchval("SELECT version_num FROM alembic_version")

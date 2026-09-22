from sqlalchemy import column, select, table

from app.database import Database

# Alembic owns this table; it is intentionally not part of application metadata.
MIGRATION_VERSION = table("alembic_version", column("version_num"))


class HealthRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def check_database(self) -> None:
        await self.conn.fetchval(select(MIGRATION_VERSION.c.version_num))

from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, func, insert, inspect, select
from testcontainers.community.postgres import PostgresContainer

from app.domain.payment_states import PaymentTask


def test_message_headers_migration_preserves_existing_context():
    with PostgresContainer("postgres:18", dbname="wellnest_test") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        config = Config("alembic.ini")
        config.attributes["connection_url"] = url
        command.upgrade(config, "f50922_trace_context")
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            previous = Table("outbox_events", MetaData(), autoload_with=engine)
            parent = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
            with engine.begin() as conn:
                conn.execute(
                    insert(previous).values(
                        id=uuid4(),
                        task=PaymentTask.create,
                        aggregate_id=uuid4(),
                        status="pending",
                        available_at=func.now(),
                        traceparent=parent,
                    )
                )
            command.upgrade(config, "head")
            current = Table("outbox_events", MetaData(), autoload_with=engine)
            with engine.connect() as conn:
                assert conn.scalar(select(current.c.headers)) == {"traceparent": parent}
                assert "traceparent" not in {
                    c["name"] for c in inspect(conn).get_columns("outbox_events")
                }
            command.downgrade(config, "f50922_trace_context")
            with engine.connect() as conn:
                assert conn.scalar(select(previous.c.traceparent)) == parent
        finally:
            engine.dispose()

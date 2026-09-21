from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql

from app.domain.payment_states import PaymentTask


def test_message_headers_migration_preserves_existing_context(database_url):
    name = "wellnest_migration_" + uuid4().hex
    parts = urlsplit(database_url)
    isolated_url = urlunsplit(parts._replace(path="/" + name))
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            config = Config("alembic.ini")
            config.attributes["connection_url"] = isolated_url
            command.upgrade(config, "f50922_trace_context")
            parent = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
            with psycopg.connect(isolated_url) as conn:
                conn.execute(
                    "INSERT INTO outbox_events"
                    "(id,task,aggregate_id,status,available_at,traceparent) "
                    "VALUES(%s,%s,%s,'pending',now(),%s)",
                    (uuid4(), PaymentTask.create, uuid4(), parent),
                )
            command.upgrade(config, "head")
            with psycopg.connect(isolated_url) as conn:
                assert conn.execute("SELECT headers FROM outbox_events").fetchone()[0] == {
                    "traceparent": parent
                }
                assert conn.execute(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='outbox_events' AND column_name='traceparent'"
                ).fetchone()[0] == 0
            command.downgrade(config, "f50922_trace_context")
            with psycopg.connect(isolated_url) as conn:
                assert conn.execute("SELECT traceparent FROM outbox_events").fetchone()[0] == parent
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))

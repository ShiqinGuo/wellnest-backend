from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base


def test_migrated_database_matches_declared_models(database_url):
    engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            differences = compare_metadata(context, Base.metadata)
            assert differences == [], f"Schema drift: {differences!r}"
    finally:
        engine.dispose()


def test_models_match_postgres_check_constraints(database_url):
    from uuid import uuid4

    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateSchema

    engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    reference = "schema_reference_" + uuid4().hex
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(CreateSchema(reference))
                Base.metadata.create_all(
                    connection.execution_options(schema_translate_map={None: reference})
                )
                inspector = inspect(connection)

                def constraints(schema):
                    return sorted(
                        (name, c["name"], c["sqltext"])
                        for name in Base.metadata.tables
                        for c in inspector.get_check_constraints(name, schema=schema)
                    )

                expected = constraints(reference)
                actual = constraints("public")
                assert actual == expected
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_drift_check_detects_a_missing_not_null_constraint(database_url):
    from alembic.operations import Operations

    engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                Operations(MigrationContext.configure(connection)).alter_column(
                    "outbox_events", "headers", nullable=True
                )
                context = MigrationContext.configure(
                    connection, opts={"compare_type": True, "compare_server_default": True}
                )
                assert compare_metadata(context, Base.metadata)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()

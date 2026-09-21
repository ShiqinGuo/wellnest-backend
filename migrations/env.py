import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.models import Base

metadata = Base.metadata

url = context.config.attributes.get("connection_url") or os.environ["WELLNEST_DATABASE_URL"]
url = url.replace("postgresql://", "postgresql+psycopg://", 1)

if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()

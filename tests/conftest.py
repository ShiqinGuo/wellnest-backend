import os
from contextlib import nullcontext
from urllib.parse import urlparse

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from app.database import ScopedDatabase
from app.dependencies.database import connection
from app.main import app
from app.payment_settings import PaymentSettings, payment_settings


@pytest.fixture(scope="session")
def database_url():
    configured = os.getenv("WELLNEST_TEST_DATABASE_URL")
    context = (
        nullcontext() if configured else PostgresContainer("postgres:18", dbname="wellnest_test")
    )
    with context as container:
        url = configured or container.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql"
        )
        if urlparse(url).path != "/wellnest_test":
            raise RuntimeError("Tests only accept a database named wellnest_test")
        previous = os.environ.get("WELLNEST_DATABASE_URL")
        os.environ["WELLNEST_DATABASE_URL"] = url
        command.upgrade(Config("alembic.ini"), "head")
        if previous is None:
            os.environ.pop("WELLNEST_DATABASE_URL")
        else:
            os.environ["WELLNEST_DATABASE_URL"] = previous
        yield url


@pytest.fixture
async def client(database_url, monkeypatch):
    monkeypatch.setenv("WELLNEST_SECURE_COOKIES", "false")
    monkeypatch.delenv("WELLNEST_ORIGIN", raising=False)

    async def test_connection():
        db = ScopedDatabase(lambda: asyncpg.connect(database_url))
        try:
            yield db
        finally:
            await db.release()

    app.dependency_overrides[connection] = test_connection
    app.dependency_overrides[payment_settings] = lambda: PaymentSettings(
        provider_url="http://test",
        merchant_url="http://test",
        public_url="http://test",
        provider_key="local-test-provider",
        webhook_secret="local-test-webhook",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()

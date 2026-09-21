from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.domain.queue_message import PaymentMessage
from app.main import app
from app.payment_settings import PaymentSettings, payment_settings
from app.worker_runtime import dispatch


@pytest.mark.parametrize("path", ["consume", "recover"])
@pytest.mark.parametrize("authorization", ["", "Bearer local-test-provider", "Bearer wrong"])
async def test_internal_routes_reject_public_credentials(client, path, authorization):
    response = await client.post(
        f"/_internal/payments/{path}",
        headers={"Authorization": authorization},
        json=PaymentMessage(event_id=uuid4(), lease_token=uuid4()).model_dump(mode="json"),
    )
    assert response.status_code == 401
    assert not any("/_internal/" in path for path in app.openapi()["paths"])


async def test_binding_dispatch_authenticates_and_releases_before_response(client, monkeypatch):
    settings = PaymentSettings(
        provider_key="provider", webhook_secret="webhook", internal_key="internal-test"
    )
    app.dependency_overrides[payment_settings] = lambda: settings
    calls = []
    payload = PaymentMessage(event_id=uuid4(), lease_token=uuid4())

    async def consume(message):
        assert message == payload
        calls.append("committed")
        return 2

    async def release():
        calls.append("released")

    async def recover(env, *, reconcile):
        assert reconcile
        calls.append("recovered")

    monkeypatch.setattr(
        "app.routers.internal_payments.delivery",
        lambda env: SimpleNamespace(consume=consume, db=SimpleNamespace(release=release)),
    )
    monkeypatch.setattr("app.routers.internal_payments.relay", recover)
    monkeypatch.setattr("app.worker_runtime.load_payment_settings", lambda env: settings)

    async def scoped_app(scope, receive, send):
        scope["env"] = SimpleNamespace()
        await app(scope, receive, send)

    class Binding:
        async def fetch(self, url, **options):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scoped_app)) as c:
                response = await c.request(
                    options["method"], url, headers=options["headers"], content=options.get("body")
                )

            async def text():
                return response.text

            return SimpleNamespace(status=response.status_code, headers=response.headers, text=text)

    env = SimpleNamespace(PAYMENT_API=Binding())
    result = await dispatch(env, "consume", payload)
    assert result.retry_after == 2 and calls == ["committed", "released"]
    assert (await dispatch(env, "recover")).retry_after is None
    assert calls[-1] == "recovered"

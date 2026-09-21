import asyncio
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from payment_helpers import settle
from pydantic.alias_generators import to_camel
from test_calculation import SAMPLE as DOMAIN_SAMPLE

from app.main import app
from app.repositories.command import CommandRepository

PROFILE = {
    "secondaryGoals": ["energy", "routine"],
    "experience": "beginner",
    "dailyActivity": "seated",
    "limitations": ["none"],
    "sleep": "variable",
    "energy": "afternoon_dip",
    "mealRhythm": "irregular_meals",
    "foodHabits": ["sweet_drinks"],
    "barrier": "time",
    "timeWindow": "evening",
}
SAMPLE = {to_camel(k): v for k, v in DOMAIN_SAMPLE.items()} | PROFILE


def key():
    return {"Idempotency-Key": str(uuid4())}


async def start(client):
    assert (await client.post("/api/sessions")).status_code == 201
    response = await client.post("/api/assessments", json={}, headers=key())
    assert response.status_code == 201, response.text
    return response.json()


async def complete(client):
    a = await start(client)
    a = (
        await client.patch(
            f"/api/assessments/{a['id']}",
            json={"expectedVersion": 0, "answers": SAMPLE, "resumeStepId": "review"},
            headers=key(),
        )
    ).json()
    r = await client.post(
        f"/api/assessments/{a['id']}/submit", json={"expectedVersion": a["version"]}, headers=key()
    )
    assert r.status_code == 200, r.text
    return a


async def test_restore_out_of_order_retries_and_conflict(client):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    headers = key()
    payload = {"expectedVersion": 0, "answers": {"activity": "light"}}
    first = await client.patch(path, json=payload, headers=headers)
    assert first.status_code == 200
    assert (await client.patch(path, json=payload, headers=headers)).json() == first.json()
    assert (await client.patch(path, json=payload, headers=key())).status_code == 409
    assert (
        await client.patch(path, json=payload | {"answers": {"age": 35}}, headers=headers)
    ).status_code == 409
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=client.cookies
    ) as restored:
        saved = (await restored.get("/api/session")).json()["assessment"]
        assert saved["answers"]["activity"] == "light"
        assert saved["resumeStepId"] == "welcome"
        assert saved["version"] == 1
    skip = await client.patch(
        path, json={"expectedVersion": 1, "resumeStepId": "review"}, headers=key()
    )
    assert skip.status_code == 422
    assert (await client.get(path)).json()["version"] == 1


async def test_concurrent_updates_do_not_lose_data(client):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    responses = await asyncio.gather(
        *[
            client.patch(path, json={"expectedVersion": 0, "answers": answer}, headers=key())
            for answer in ({"age": 35}, {"activity": "moderate"})
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    saved = (await client.get(path)).json()
    assert saved["version"] == 1
    missing = {"activity": "moderate"} if saved["answers"]["age"] else {"age": 35}
    assert (
        await client.patch(path, json={"expectedVersion": 1, "answers": missing}, headers=key())
    ).status_code == 200
    saved = (await client.get(path)).json()
    assert saved["answers"]["age"] == 35 and saved["answers"]["activity"] == "moderate"


async def test_access_payment_and_replay(client):
    a = await complete(client)
    path = f"/api/assessments/{a['id']}/result"
    free = (await client.get(path)).json()
    assert set(free) == {
        "access",
        "assessmentId",
        "bmi",
        "bmiCategory",
        "summary",
        "lockedFeatures",
        "planPreview",
    }
    headers = key()
    payment = await client.post("/api/payments", json={}, headers=headers)
    assert payment.status_code == 201
    assert (await client.post("/api/payments", json={}, headers=headers)).json() == payment.json()
    assert (await client.post("/api/payments", json={}, headers=key())).json() == payment.json()
    assert (await client.get(path)).json()["access"] == "free"
    await settle(client, payment.json()["id"])
    member = (await client.get(path)).json()
    assert member["access"] == "member" and len(member["calculation"]["projection"]) > 1
    assert "no-store" in (await client.get(path)).headers["cache-control"]
    assert (
        await client.patch(
            f"/api/assessments/{a['id']}",
            json={"expectedVersion": 2, "answers": {"age": 36}},
            headers=key(),
        )
    ).status_code == 409
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as other:
        assert (await other.get(path)).status_code == 401
        await other.post("/api/sessions")
        assert (await other.get(path)).status_code == 404
        assert (await other.get(f"/api/assessments/{a['id']}")).status_code == 404


@pytest.mark.parametrize(
    "answer",
    [
        {"age": "35"},
        {"age": None, "injected": 1},
        {"weightKg": False},
        {"heightCm": 0},
        {"weightKg": "1 OR 1=1"},
        {"subscriptionStatus": "active"},
    ],
)
async def test_http_validation(client, answer):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    assert (
        await client.patch(path, json={"expectedVersion": 0, "answers": answer}, headers=key())
    ).status_code == 422
    assert (await client.get(path)).json()["version"] == 0


async def test_incomplete_payment_origin_and_expiry(client, database_url):
    a = await start(client)
    assert (await client.post("/api/payments", json={}, headers=key())).status_code == 409
    assert (
        await client.post(
            f"/api/assessments/{a['id']}/submit", json={"expectedVersion": 0}, headers=key()
        )
    ).status_code == 422
    assert (
        await client.post("/api/payments", json={}, headers=key() | {"Origin": "https://evil.example"})
    ).status_code == 403
    session = (await client.get("/api/session")).json()["sessionId"]
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            "UPDATE auth_sessions SET expires_at=now()-interval '1 second' WHERE id=$1",
            UUID(session),
        )
    finally:
        await conn.close()
    assert (await client.get("/api/session")).status_code == 401


async def test_failed_receipt_rolls_back_payment(client, monkeypatch):
    a = await complete(client)
    original = CommandRepository.record

    async def fail(*args, **kwargs):
        raise RuntimeError("Injected receipt failure")

    monkeypatch.setattr(CommandRepository, "record", fail)
    response = await client.post("/api/payments", json={}, headers=key())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "Injected" not in response.text
    assert (await client.get("/api/session")).json()["subscriptionStatus"] == "inactive"
    assert (await client.get(f"/api/assessments/{a['id']}/result")).json()["access"] == "free"
    monkeypatch.setattr(CommandRepository, "record", original)
    assert (await client.post("/api/payments", json={}, headers=key())).status_code == 201

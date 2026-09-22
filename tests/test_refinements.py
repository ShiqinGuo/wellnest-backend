import asyncio
import json
from datetime import date
from uuid import UUID

import asyncpg
from payment_helpers import pay
from sqlalchemy import func, select, update
from test_flows import SAMPLE, complete, key, start
from test_refactor_and_jev import StubTransport, answers

from app.database import ScopedDatabase
from app.dependencies.database import connection
from app.dependencies.services import get_jev
from app.domain.assessment import CompleteAnswers
from app.domain.calculation import assess
from app.main import app
from app.models import Assessment, AssessmentResult, GuidanceAttempt
from app.providers.typesafe import JevClient


def test_male_independent_reference():
    # 10*80 + 6.25*180 - 5*40 + 5 = 1730; activity 1.55 -> 2682.
    result = assess(
        CompleteAnswers(
            sex="male",
            goal="gain",
            age=40,
            height_cm=180,
            weight_kg=80,
            target_weight_kg=85,
            activity="moderate",
        ),
        today=date(2026, 1, 1),
    )
    assert result.resting_kcal == 1730
    assert result.maintenance_kcal == 2682
    assert result.suggested_kcal == 2932
    assert result.predicted_goal_date == date(2026, 6, 4)


async def test_real_deadline_cancels_waiting_transport():
    cancelled = asyncio.Event()

    class HangingTransport:
        async def post(self, body):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    result = await asyncio.wait_for(
        JevClient(HangingTransport(), timeout_seconds=0.02).judge(answers()), timeout=1
    )
    assert result.failure_code == "timeout"
    assert cancelled.is_set()


async def test_inference_releases_database_connection(client):
    original = app.dependency_overrides[connection]
    databases = []

    async def tracked_database():
        async for db in original():
            connect = db.connect
            db.opened = []

            async def tracked_connect(connect=connect, db=db):
                conn = await connect()
                db.opened.append(conn)
                return conn

            db.connect = tracked_connect
            databases.append(db)
            yield db

    class InspectingTransport(StubTransport):
        async def post(self, body):
            assert databases
            assert all(db.active is None for db in databases)
            assert all(conn.is_closed() for db in databases for conn in db.opened)
            return await super().post(body)

    app.dependency_overrides[connection] = tracked_database
    app.dependency_overrides[get_jev] = lambda: JevClient(InspectingTransport())
    await complete(client)
    # Submission has exactly one read phase and one commit phase, not one connection per SQL.
    assert max(len(db.opened) for db in databases) == 2
    assert all(conn.is_closed() for db in databases for conn in db.opened)


async def test_maintain_derives_target_and_skips_redundant_step(client):
    assessment = await start(client)
    payload = SAMPLE | {"goal": "maintain", "targetWeightKg": None}
    path = f"/api/assessments/{assessment['id']}"
    saved = await client.patch(
        path,
        json={
            "expectedVersion": 0,
            "answers": payload,
            "resumeStepId": "activity",
        },
        headers=key(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["answers"]["targetWeightKg"] == SAMPLE["weightKg"]
    assert (
        await client.post(path + "/submit", json={"expectedVersion": 1}, headers=key())
    ).status_code == 200


async def test_guidance_retry_auth_replay_snapshot_and_version(client, database_url):
    failing = StubTransport(error=TimeoutError())
    app.dependency_overrides[get_jev] = lambda: JevClient(failing)
    assessment = await complete(client)
    path = f"/api/assessments/{assessment['id']}"
    retry_path = path + "/guidance/retry"
    body = {"expectedVersion": 0}
    assert (await client.post(retry_path, json=body, headers=key())).status_code == 403
    await pay(client)
    before = (await client.get(path + "/result")).json()["calculation"]
    working = StubTransport()
    app.dependency_overrides[get_jev] = lambda: JevClient(working)
    headers = key()
    result = await client.post(retry_path, json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "ready" and result.json()["revision"] == 1
    assert (await client.post(retry_path, json=body, headers=headers)).json() == result.json()
    assert working.calls == 1
    assert (await client.post(retry_path, json=body, headers=key())).status_code == 409
    assert (
        await client.post(retry_path, json={"expectedVersion": 1}, headers=key())
    ).status_code == 409
    after = (await client.get(path + "/result")).json()["calculation"]
    assert {k: v for k, v in before.items() if k != "guidance"} == {
        k: v for k, v in after.items() if k != "guidance"
    }
    conn = ScopedDatabase(lambda: asyncpg.connect(database_url))
    try:
        original_status = await conn.fetchval(
            select(AssessmentResult.calculation["guidance"]["status"].astext)
            .select_from(AssessmentResult)
            .where(AssessmentResult.assessment_id == UUID(assessment["id"]))
        )
        assert original_status == "unavailable"
        assert (
            await conn.fetchval(
                select(func.count())
                .select_from(GuidanceAttempt)
                .where(GuidanceAttempt.assessment_id == UUID(assessment["id"]))
            )
            == 1
        )
    finally:
        await conn.release()


async def test_concurrent_guidance_retries_keep_one_revision(client):
    app.dependency_overrides[get_jev] = lambda: JevClient(StubTransport(error=TimeoutError()))
    assessment = await complete(client)
    await pay(client)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class ConcurrentTransport(StubTransport):
        async def post(self, body):
            nonlocal calls
            calls += 1
            if calls == 2:
                entered.set()
            await release.wait()
            return await super().post(body)

    app.dependency_overrides[get_jev] = lambda: JevClient(ConcurrentTransport())
    path = f"/api/assessments/{assessment['id']}/guidance/retry"
    tasks = [
        asyncio.create_task(client.post(path, json={"expectedVersion": 0}, headers=key()))
        for _ in range(2)
    ]
    try:
        await asyncio.wait_for(entered.wait(), 3)
    finally:
        release.set()
    responses = await asyncio.gather(*tasks)
    assert sorted(response.status_code for response in responses) == [200, 409]


async def test_unknown_flow_cannot_silently_use_current_rules(client, database_url):
    assessment = await start(client)
    conn = ScopedDatabase(lambda: asyncpg.connect(database_url))
    try:
        await conn.execute(
            update(Assessment)
            .where(Assessment.id == UUID(assessment["id"]))
            .values(flow_version="future-v99")
        )
    finally:
        await conn.release()
    path = f"/api/assessments/{assessment['id']}"
    for endpoint, method, body in [
        (path, "PATCH", {"expectedVersion": 0, "answers": SAMPLE}),
        (path + "/submit", "POST", {"expectedVersion": 0}),
    ]:
        response = await client.request(method, endpoint, json=body, headers=key())
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "UNSUPPORTED_FLOW"


async def test_historical_result_is_not_recalculated_after_rules_upgrade(client, database_url):
    assessment = await complete(client)
    await pay(client)
    conn = ScopedDatabase(lambda: asyncpg.connect(database_url))
    try:
        row = await conn.fetchval(
            select(AssessmentResult.calculation)
            .select_from(AssessmentResult)
            .where(AssessmentResult.assessment_id == UUID(assessment["id"]))
        )
        snapshot = json.loads(row)
        snapshot["algorithm_version"] = "wellness-v1"
        snapshot["predicted_goal_date"] = "2026-09-17"
        snapshot.pop("guidance", None)
        await conn.execute(
            update(AssessmentResult)
            .where(AssessmentResult.assessment_id == UUID(assessment["id"]))
            .values(calculation=json.loads(json.dumps(snapshot)))
        )
    finally:
        await conn.release()
    result = (await client.get(f"/api/assessments/{assessment['id']}/result")).json()
    assert result["calculation"]["algorithmVersion"] == "wellness-v1"
    assert result["calculation"]["predictedGoalDate"] == "2026-09-17"
    assert result["calculation"]["guidance"] is None

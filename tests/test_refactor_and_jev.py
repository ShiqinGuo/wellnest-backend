import asyncio
import hashlib
import json

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from payment_helpers import pay
from test_flows import SAMPLE, complete, key, start

from app.dependencies.services import get_jev
from app.domain.assessment import CompleteAnswers
from app.main import app
from app.providers.typesafe import JevClient, JevTransportError

VALID = {
    "model": "jev-test",
    "answers": {
        "focus": {
            "type": "choice",
            "choice": "movement_habit",
            "confidence": 0.9,
            "probabilities": {
                "movement_habit": 0.95,
                "meal_routine": 0.02,
                "consistency": 0.02,
                "insufficient_context": 0.01,
            },
        },
        "effort": {"type": "score", "score": 1.2, "confidence": 0.8},
    },
}


class StubTransport:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else VALID
        self.error = error
        self.calls = 0

    async def post(self, body):
        self.calls += 1
        state = json.loads(body)["state"]
        assert {"goal", "activity", "relative_target_change", "food_habits", "limitations"} <= set(
            state
        )
        assert not {"sex", "age", "height_cm", "weight_kg"} & set(state)
        if self.error:
            raise self.error
        return json.dumps(self.result)


def answers():
    return CompleteAnswers(
        sex="female",
        goal="lose",
        age=35,
        height_cm=165,
        weight_kg=75,
        target_weight_kg=65,
        activity="light",
    )


@pytest.mark.parametrize(
    "error,code", [(TimeoutError(), "timeout"), (JevTransportError("upstream_429"), "upstream_429")]
)
async def test_jev_unavailable_is_explicit(error, code):
    result = await JevClient(StubTransport(error=error)).judge(answers())
    assert result.status == "unavailable" and result.failure_code == code
    assert result.focus is None


@pytest.mark.parametrize("change", ["unknown_choice", "missing_answer", "nan", "bad_distribution"])
async def test_jev_rejects_invalid_response(change):
    raw = json.loads(json.dumps(VALID))
    if change == "unknown_choice":
        raw["answers"]["focus"]["choice"] = "prescribe_drug"
    elif change == "missing_answer":
        del raw["answers"]["effort"]
    elif change == "nan":
        raw["answers"]["effort"]["score"] = float("nan")
    else:
        raw["answers"]["focus"]["probabilities"]["movement_habit"] = 0.1
    result = await JevClient(StubTransport(raw)).judge(answers())
    assert result.status == "unavailable" and result.failure_code == "invalid_response"


async def test_low_confidence_does_not_present_decision():
    raw = json.loads(json.dumps(VALID))
    raw["answers"]["focus"]["confidence"] = 0.1
    raw["answers"]["effort"]["confidence"] = 0.2
    result = await JevClient(StubTransport(raw)).judge(answers())
    assert result.status == "uncertain" and result.focus is None and result.effort_score is None


async def test_jev_persisted_and_member_only(client):
    transport = StubTransport()
    app.dependency_overrides[get_jev] = lambda: JevClient(transport)
    assessment = await complete(client)
    path = f"/api/assessments/{assessment['id']}/result"
    free = (await client.get(path)).json()
    assert "guidance" not in json.dumps(free)
    await pay(client)
    member = (await client.get(path)).json()
    assert member["calculation"]["guidance"]["focus"] == "movement_habit"
    assert member["calculation"]["guidance"]["model"] == "jev-test"
    assert member["calculation"]["suggestedKcal"] == 1689
    assert (await client.get(path)).json() == member
    assert transport.calls == 1


async def test_inference_does_not_hold_lock_and_rechecks_version(client):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingTransport(StubTransport):
        async def post(self, body):
            entered.set()
            await release.wait()
            return await super().post(body)

    app.dependency_overrides[get_jev] = lambda: JevClient(WaitingTransport())
    assessment = await start(client)
    path = f"/api/assessments/{assessment['id']}"
    assert (
        await client.patch(path, json={"expectedVersion": 0, "answers": SAMPLE}, headers=key())
    ).status_code == 200
    task = asyncio.create_task(
        client.post(path + "/submit", json={"expectedVersion": 1}, headers=key())
    )
    try:
        await asyncio.wait_for(entered.wait(), 3)
        changed = await asyncio.wait_for(
            client.patch(path, json={"expectedVersion": 1, "answers": {"age": 36}}, headers=key()),
            3,
        )
        assert changed.status_code == 200
    finally:
        release.set()
    assert (await task).status_code == 409
    assert (await client.get(path + "/result")).status_code == 404


async def test_legacy_receipt_replay(client, database_url):
    assessment = await start(client)
    headers = key()
    path = f"/api/assessments/{assessment['id']}"
    payload = {"expectedVersion": 0, "answers": {"age": 35}}
    first = (await client.patch(path, json=payload, headers=headers)).json()
    # Persist the exact pre-refactor receipt shape, including its old fingerprint.
    fingerprint = hashlib.sha256(
        json.dumps({"expected_version": 0, "answers": {"age": 35}}, sort_keys=True).encode()
    ).hexdigest()
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            "UPDATE command_receipts SET response=$1::jsonb,fingerprint=$2 "
            "WHERE command=$3 AND key=$4",
            json.dumps(first),
            fingerprint,
            f"assessment.patch:{assessment['id']}",
            headers["Idempotency-Key"],
        )
    finally:
        await conn.close()
    replay = await client.patch(path, json=payload, headers=headers)
    assert replay.status_code == 200 and replay.json() == first
    assert (await client.get(path)).json()["version"] == 1


def test_declarative_models_match_migrated_postgres(database_url):
    config = Config("alembic.ini")
    config.attributes["connection_url"] = database_url
    command.check(config)

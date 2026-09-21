import json
from uuid import UUID

import asyncpg
import pytest
from payment_helpers import pay
from pydantic import ValidationError
from pydantic.alias_generators import to_snake
from test_flows import PROFILE, SAMPLE, complete, key, start
from test_refactor_and_jev import VALID

from app.domain.assessment import Answers, CompleteAnswers
from app.domain.enums import FlowVersion
from app.domain.plan import build_plan
from app.providers.typesafe import JevClient


@pytest.mark.parametrize(
    "values",
    [
        {"limitations": ["none", "back"]},
        {"food_habits": ["none", "sweets"]},
        {"secondary_goals": []},
        {"food_habits": ["sweets", "sweets"]},
        {"daily_activity": "unknown"},
        {"energy": 123},
        {"barrier": "motivation", "time_window": "evening"},
    ],
)
def test_profile_rejects_invalid_values(values):
    with pytest.raises(ValidationError):
        Answers.model_validate(values)


def test_plan_changes_with_evidence_and_respects_limitations():
    a = Answers.model_validate({to_snake(k): v for k, v in SAMPLE.items()})
    plan = build_plan(a)
    assert "seated" in [m.code for m in plan.cards[0].reason]
    assert plan.cards[2].reason[0].params.meal_rhythm == "irregular_meals"
    assert plan.cards[3].action[0].params.time_window == "evening"
    a = Answers.model_validate(
        a.model_dump()
        | {
            "limitations": ["knees"],
            "meal_rhythm": "regular_meals",
            "food_habits": ["none"],
            "barrier": "motivation",
            "time_window": None,
        }
    )
    changed = build_plan(a)
    assert changed.boundaries[0].params.limitations == ["knees"]
    assert [m.code for m in changed.cards[0].action] == ["seek_advice"]
    assert changed.cards[2].action[0].code == "keep_meals"
    assert "timeWindow" not in changed.cards[3].source_fields
    assert "evening" not in changed.model_dump_json()
    assert build_plan(Answers()) is None


async def test_conditional_answer_clear_and_replay(client):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    saved = await client.patch(
        path,
        json={"expectedVersion": 0, "answers": SAMPLE, "resumeStepId": "time_window"},
        headers=key(),
    )
    assert saved.status_code == 200, saved.text
    a = saved.json()
    assert a["answers"]["timeWindow"] == "evening"
    assert (await client.get("/api/session")).json()["assessment"]["resumeStepId"] == "time_window"
    headers = key()
    command = {"expectedVersion": a["version"], "answers": {"barrier": "motivation"}}
    changed = await client.patch(path, json=command, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["answers"]["timeWindow"] is None
    assert changed.json()["resumeStepId"] == "habits_feedback"
    assert "evening" not in json.dumps(changed.json()["planPreview"], ensure_ascii=False)
    assert (await client.patch(path, json=command, headers=headers)).json() == changed.json()
    a = changed.json()
    denied = await client.patch(
        path,
        json={"expectedVersion": a["version"], "answers": {"timeWindow": "morning"}},
        headers=key(),
    )
    assert denied.status_code == 422
    changed = await client.patch(
        path, json={"expectedVersion": a["version"], "answers": {"barrier": "time"}}, headers=key()
    )
    assert changed.json()["resumeStepId"] == "time_window"
    assert "timeWindow" in changed.json()["missingFields"]
    # Single-field PATCH works without repeating its persisted parent.
    a = changed.json()
    changed = await client.patch(
        path,
        json={
            "expectedVersion": a["version"],
            "answers": {"timeWindow": "morning"},
            "resumeStepId": "habits_feedback",
        },
        headers=key(),
    )
    assert changed.status_code == 200, changed.text
    assert (
        changed.json()["planPreview"]["cards"][3]["action"][0]["params"]["timeWindow"] == "morning"
    )


async def test_new_flow_requires_lifestyle_and_null_clears(client):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    body = {k: v for k, v in SAMPLE.items() if k not in PROFILE}
    saved = await client.patch(path, json={"expectedVersion": 0, "answers": body}, headers=key())
    assert saved.status_code == 200
    rejected = await client.post(path + "/submit", json={"expectedVersion": 1}, headers=key())
    assert rejected.status_code == 422
    assert "secondaryGoals" in rejected.text
    saved = await client.patch(
        path,
        json={"expectedVersion": 1, "answers": PROFILE, "resumeStepId": "review"},
        headers=key(),
    )
    assert saved.status_code == 200
    saved = await client.patch(
        path, json={"expectedVersion": 2, "answers": {"foodHabits": None}}, headers=key()
    )
    assert saved.json()["resumeStepId"] == "food_habits"
    assert "foodHabits" in saved.json()["missingFields"]
    assert len(saved.json()["planPreview"]["cards"]) == 3


async def test_lifestyle_snapshot_free_preview_and_member_fields(client, database_url):
    a = await complete(client)
    path = f"/api/assessments/{a['id']}/result"
    free = (await client.get(path)).json()
    assert len(free["planPreview"]["cards"]) == 4
    assert not {"calculation", "suggestedKcal", "projection", "predictedGoalDate"} & free.keys()
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            "SELECT input_snapshot,calculation FROM assessment_results WHERE assessment_id=$1",
            UUID(a["id"]),
        )
        assert json.loads(row["input_snapshot"])["food_habits"] == ["sweet_drinks"]
        assert (
            json.loads(row["calculation"])["plan_preview"]["rules_version"] == "lifestyle-plan-v1"
        )
    finally:
        await conn.close()
    assert (await pay(client)).status_code == 201
    member = (await client.get(path)).json()
    assert member["planPreview"] == free["planPreview"]
    assert "projection" in member["calculation"]


async def test_jev_receives_real_habit_answers():
    class Capture:
        async def post(self, body):
            state = json.loads(body)["state"]
            assert state["meal_rhythm"] == "irregular_meals"
            assert state["food_habits"] == ["sweet_drinks"]
            assert state["time_window"] == "evening"
            return json.dumps(VALID)

    answers = CompleteAnswers.model_validate({to_snake(k): v for k, v in SAMPLE.items()})
    assert (await JevClient(Capture()).judge(answers)).status == "ready"


@pytest.mark.parametrize("version", [FlowVersion.legacy, FlowVersion.guided])
async def test_old_flow_submit_without_lifestyle(client, database_url, version):
    a = await start(client)
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            "UPDATE assessments SET flow_version=$1 WHERE id=$2", version, UUID(a["id"])
        )
    finally:
        await conn.close()
    path = f"/api/assessments/{a['id']}"
    saved = await client.patch(
        path,
        json={
            "expectedVersion": 0,
            "answers": {k: v for k, v in SAMPLE.items() if k not in PROFILE},
            "resumeStepId": "review",
        },
        headers=key(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["missingFields"] == []
    assert (
        await client.post(path + "/submit", json={"expectedVersion": 1}, headers=key())
    ).status_code == 200
    assert (await client.get(path + "/result")).json()["planPreview"] is None


async def test_postgres_rejects_invalid_profile_values(client, database_url):
    a = await start(client)
    conn = await asyncpg.connect(database_url)
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE assessments SET sleep='impossible' WHERE id=$1", UUID(a["id"])
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE assessments SET limitations=ARRAY['none','knees'] WHERE id=$1",
                UUID(a["id"]),
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE assessments SET time_window='evening' WHERE id=$1", UUID(a["id"])
            )
    finally:
        await conn.close()

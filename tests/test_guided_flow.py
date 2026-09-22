from uuid import UUID

from pydantic.alias_generators import to_camel
from sqlalchemy import update
from test_flows import DOMAIN_SAMPLE, key, start

from app.database import ScopedDatabase
from app.domain.assessment import Answers
from app.domain.enums import FlowVersion, Step
from app.domain.flow import AssessmentNavigation
from app.models import Assessment


async def test_guidance_page_persists_and_changes_with_answers(client):
    a = await start(client)
    assert a["flowVersion"] == FlowVersion.lifestyle
    path = f"/api/assessments/{a['id']}"
    response = await client.patch(
        path,
        json={
            "expectedVersion": a["version"],
            "answers": {"goal": "lose"},
            "resumeStepId": "goal_feedback",
        },
        headers=key(),
    )
    assert response.status_code == 200, response.text
    a = response.json()
    saved = (await client.get("/api/session")).json()["assessment"]
    assert saved["resumeStepId"] == "goal_feedback"
    assert saved["answers"]["goal"] == "lose"
    # A feedback page is not permission to jump over unanswered questions.
    denied = await client.patch(
        path,
        json={
            "expectedVersion": a["version"],
            "resumeStepId": "activity_feedback",
        },
        headers=key(),
    )
    assert denied.status_code == 422
    changed = await client.patch(
        path,
        json={
            "expectedVersion": a["version"],
            "answers": {"goal": "maintain"},
            "resumeStepId": "goal_feedback",
        },
        headers=key(),
    )
    assert changed.status_code == 200
    assert changed.json()["answers"]["goal"] == "maintain"
    assert changed.json()["resumeStepId"] == "goal_feedback"


def test_legacy_navigation_is_unchanged():
    answers = Answers(sex="female")
    assert (
        AssessmentNavigation.transition(Step.sex, Step.goal, answers, FlowVersion.legacy)
        == Step.goal
    )
    complete = Answers.model_validate(
        {
            "sex": "female",
            "goal": "lose",
            "age": 35,
            "height_cm": 165,
            "weight_kg": 75,
            "target_weight_kg": 65,
            "activity": "light",
        }
    )
    assert (
        AssessmentNavigation.transition(
            Step.target, Step.target_feedback, complete, FlowVersion.guided
        )
        == Step.target_feedback
    )


async def test_legacy_draft_remains_editable(client, database_url):
    import asyncpg

    a = await start(client)
    conn = ScopedDatabase(lambda: asyncpg.connect(database_url))
    try:
        await conn.execute(
            update(Assessment)
            .where(Assessment.id == UUID(a["id"]))
            .values(flow_version=FlowVersion.legacy)
        )
    finally:
        await conn.release()
    result = await client.patch(
        f"/api/assessments/{a['id']}",
        json={
            "expectedVersion": a["version"],
            "answers": {to_camel(k): v for k, v in DOMAIN_SAMPLE.items()},
            "resumeStepId": "review",
        },
        headers=key(),
    )
    assert result.status_code == 200, result.text
    assert result.json()["flowVersion"] == FlowVersion.legacy

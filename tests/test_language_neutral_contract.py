import json
import re
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from payment_helpers import pay
from test_flows import complete


def assert_language_neutral(value):
    assert not re.search(r"[\u4e00-\u9fff]", json.dumps(value, ensure_ascii=False))


@pytest.mark.parametrize("legacy", [False, True])
async def test_session_and_result_are_language_neutral(client, database_url, legacy):
    assessment = await complete(client)
    identifier = UUID(assessment["id"])
    conn = await asyncpg.connect(database_url)
    try:
        if legacy:
            raw = json.loads(
                await conn.fetchval(
                    "SELECT calculation FROM assessment_results WHERE assessment_id=$1", identifier
                )
            )
            raw["plan_preview"] = json.loads(
                (Path(__file__).parent / "fixtures/legacy_plan_v1.json").read_text(encoding="utf8")
            )
            raw["bmi_category"] = "参考范围内"
            raw["assumptions"] = ["采用成人 Mifflin–St Jeor 公式及简化活动系数。"]
            await conn.execute(
                "UPDATE assessment_results SET calculation=$2::jsonb WHERE assessment_id=$1",
                identifier,
                json.dumps(raw),
            )
        frozen = await conn.fetchval(
            "SELECT calculation FROM assessment_results WHERE assessment_id=$1", identifier
        )
        path = f"/api/assessments/{identifier}/result"
        for endpoint in ["/api/session", path]:
            english = await client.get(endpoint, headers={"Accept-Language": "en"})
            chinese = await client.get(endpoint, headers={"Accept-Language": "zh-CN"})
            assert english.status_code == chinese.status_code == 200
            assert english.json() == chinese.json()
            assert_language_neutral(english.json())
        free = (await client.get(path)).json()
        assert "calculation" not in free
        assert free["planPreview"]["formatVersion"] == 2
        paid = await pay(client)
        assert paid.status_code == 201, paid.text
        member = (await client.get(path)).json()
        assert member["access"] == "member"
        assert member["planPreview"] == free["planPreview"]
        assert_language_neutral(member)
        original = json.loads(frozen)
        assert member["calculation"]["suggestedKcal"] == original["suggested_kcal"]
        assert member["calculation"]["predictedGoalDate"] == original["predicted_goal_date"]
        assert (
            await conn.fetchval(
                "SELECT calculation FROM assessment_results WHERE assessment_id=$1", identifier
            )
            == frozen
        )
    finally:
        await conn.close()

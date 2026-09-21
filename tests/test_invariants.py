import asyncio

from test_flows import PROFILE, complete, key, start


async def test_merged_target_rules_and_clear_resume(client):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    response = await client.patch(
        path,
        json={
            "expectedVersion": 0,
            "answers": {
                **PROFILE,
                "sex": "female",
                "goal": "lose",
                "age": 35,
                "heightCm": 165,
                "weightKg": 75,
                "targetWeightKg": 65,
                "activity": "light",
            },
            "resumeStepId": "review",
        },
        headers=key(),
    )
    assert response.status_code == 200
    # Each patch is valid alone, but must also be validated against persisted inputs.
    invalid = await client.patch(
        path, json={"expectedVersion": 1, "answers": {"weightKg": 60}}, headers=key()
    )
    assert invalid.status_code == 422
    assert (await client.get(path)).json()["answers"]["weightKg"] == 75
    clear = await client.patch(
        path, json={"expectedVersion": 1, "answers": {"age": None}}, headers=key()
    )
    assert clear.status_code == 200
    assert clear.json()["resumeStepId"] == "age"
    assert "age" in clear.json()["missingFields"]


async def test_parallel_payment_and_new_assessment_preserve_history(client):
    a = await complete(client)
    responses = await asyncio.gather(
        *[client.post("/api/payments", json={}, headers=key()) for _ in range(3)]
    )
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    old_path = f"/api/assessments/{a['id']}/result"
    old_result = (await client.get(old_path)).json()
    new = await client.post("/api/assessments", json={"sourceAssessmentId": a["id"]}, headers=key())
    assert new.status_code == 201
    assert new.json()["id"] != a["id"]
    assert new.json()["status"] == "draft"
    assert new.json()["answers"] == a["answers"]
    assert (await client.get(old_path)).json() == old_result


async def test_json_nonfinite_and_unknown_fields_do_not_persist(client):
    a = await start(client)
    path = f"/api/assessments/{a['id']}"
    for literal in ("NaN", "Infinity", "-Infinity"):
        response = await client.patch(
            path,
            content='{"expectedVersion":0,"answers":{"heightCm":' + literal + "}}",
            headers=key() | {"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "input" not in response.json()["error"]["details"]
    assert (await client.get(path)).json()["version"] == 0

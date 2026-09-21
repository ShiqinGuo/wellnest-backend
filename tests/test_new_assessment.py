from test_flows import key, start


async def test_explicit_new_preserves_draft_and_replays(client):
    old = await start(client)
    old_path = f"/api/assessments/{old['id']}"
    saved = await client.patch(
        old_path, json={"expectedVersion": 0, "answers": {"age": 35}}, headers=key()
    )
    assert saved.status_code == 200
    resumed = await client.post("/api/assessments", json={}, headers=key())
    assert resumed.json()["id"] == old["id"]
    headers = key()
    new = await client.post("/api/assessments", json={"startNew": True}, headers=headers)
    assert new.status_code == 201
    fresh = new.json()
    assert fresh["id"] != old["id"]
    assert fresh["flowVersion"] == "lifestyle-v3"
    assert fresh["answers"]["age"] is None
    replay = await client.post("/api/assessments", json={"startNew": True}, headers=headers)
    assert replay.json() == fresh
    assert (await client.get(old_path)).json()["answers"]["age"] == 35
    assert (await client.get("/api/session")).json()["assessment"]["id"] == fresh["id"]
    rejected = await client.post("/api/assessments", json={"startNew": "false"}, headers=key())
    assert rejected.status_code == 422

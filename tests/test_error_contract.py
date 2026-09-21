from uuid import uuid4

from app.errors import ErrorCode


async def test_auth_origin_and_validation_use_the_same_error_envelope(client):
    missing = await client.get("/api/session")
    blocked = await client.post("/api/sessions", headers={"Origin": "https://invalid.example"})
    await client.post("/api/sessions")
    invalid = await client.post(
        "/api/assessments",
        headers={"Idempotency-Key": str(uuid4())},
        json={"unexpected": "private-health-data"},
    )
    for response, code in (
        (missing, ErrorCode.session_required),
        (blocked, ErrorCode.origin_rejected),
        (invalid, ErrorCode.validation_error),
    ):
        assert response.status_code == code.status
        error = response.json()["error"]
        assert error["code"] == code.value
        assert error["message"] == code.message
        assert error["requestId"] == response.headers["x-request-id"]
        assert "details" in error
        assert "private-health-data" not in response.text
    assert invalid.json()["error"]["details"]["issues"][0]["code"] == "extra_forbidden"

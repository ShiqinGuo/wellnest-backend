"""Black-box payment test against HTTP + actual Cloudflare Queue handlers."""

import argparse
import json
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18090")
    args = parser.parse_args()
    confirmation_trace_id = None
    with httpx.Client(base_url=args.base_url, timeout=15) as client:

        def post(path, body=None, key=None):
            nonlocal confirmation_trace_id
            response = client.post(
                path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
            )
            response.raise_for_status()
            if path.endswith("/confirm"):
                confirmation_trace_id = response.headers.get("X-Trace-ID")
            return response.json()

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        post("/api/sessions")
        assessment = post("/api/assessments", {})
        path = f"/api/assessments/{assessment['id']}"
        response = client.patch(
            path,
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "expectedVersion": 0,
                "resumeStepId": "review",
                "answers": {
                    "sex": "female",
                    "goal": "lose",
                    "age": 35,
                    "heightCm": 165,
                    "weightKg": 75,
                    "targetWeightKg": 65,
                    "activity": "light",
                    "secondaryGoals": ["energy"],
                    "experience": "beginner",
                    "dailyActivity": "seated",
                    "limitations": ["none"],
                    "sleep": "variable",
                    "energy": "afternoon_dip",
                    "mealRhythm": "regular_meals",
                    "foodHabits": ["sweet_drinks"],
                    "barrier": "motivation",
                },
            },
        )
        response.raise_for_status()
        post(path + "/submit", {"expectedVersion": response.json()["version"]})
        free = get(path + "/result")
        assert free["access"] == "free" and "calculation" not in free
        operation_key = str(uuid4())
        created = post("/api/payments", {}, operation_key)
        assert created["status"] == "pending" and created["checkoutUrl"] is None
        payment_path = f"/api/payments/{created['id']}"

        def poll(predicate):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                value = get(payment_path)
                if predicate(value):
                    return value
                time.sleep(0.5)
            raise AssertionError("Payment worker did not converge within 90 seconds")

        ready = poll(lambda value: value["nextAction"] == "open_checkout")
        assert get(path + "/result")["access"] == "free"
        checkout_path = urlsplit(ready["checkoutUrl"]).path
        paid = post(checkout_path + "/confirm", {"outcome": "succeeded"})
        assert paid["status"] == "succeeded"
        poll(lambda value: value["status"] == "succeeded")
        assert get(path + "/result")["access"] == "member"
        assert "projection" in get(path + "/result")["calculation"]
        assert post("/api/payments", {}, operation_key) == created
        assert client.post("/pay", json={}).status_code == 404
        print(
            json.dumps(
                {
                    "paymentId": created["id"],
                    "confirmationTraceId": confirmation_trace_id,
                    "status": "passed",
                    "transport": "HTTP + PostgreSQL outbox + Cloudflare Queues",
                    "verified": [
                        "pending",
                        "provider_checkout",
                        "signed_webhook",
                        "member_result",
                        "replay",
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

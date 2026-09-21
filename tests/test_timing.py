import asyncio
import json

from app.timing import Phase, RequestTiming, current_timing, measure


async def test_parallel_timing_context_isolation_and_failure():
    async def run(count):
        timing = RequestTiming()
        token = current_timing.set(timing)
        try:
            for _ in range(count):
                try:
                    with measure(Phase.query):
                        await asyncio.sleep(0)
                        raise ValueError("failed query")
                except ValueError:
                    pass
            return timing
        finally:
            current_timing.reset(token)

    first, second = await asyncio.gather(run(1), run(3))
    assert first.counts == {"db_query": 1}
    assert second.counts == {"db_query": 3}
    assert current_timing.get() is None


async def test_request_timings_do_not_log_cookie_or_body(client, capsys):
    response = await client.post("/api/sessions", json={})
    assert response.status_code == 201
    assert "db_connect;dur=" in response.headers["server-timing"]
    lines = capsys.readouterr().out.splitlines()
    event = next(json.loads(line) for line in lines if '"event": "request_timing"' in line)
    assert event["counts"]["db_connect"] == 1
    assert event["counts"]["db_close"] == 1
    assert event["route"] == "/api/sessions"
    assert response.cookies["wellnest_session"] not in json.dumps(event)
    assert current_timing.get() is None

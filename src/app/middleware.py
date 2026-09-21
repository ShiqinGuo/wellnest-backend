from uuid import uuid4

from starlette.datastructures import URL, Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.settings import runtime_value


class RequestPolicy:
    """Pure ASGI: do not create a task group and stream adapter for every request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        origin = Headers(scope=scope).get("origin")
        url = URL(scope=scope)
        allowed = runtime_value(scope.get("env"), "WELLNEST_ORIGIN", f"{url.scheme}://{url.netloc}")

        async def send_with_headers(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        if scope["method"] not in {"GET", "HEAD", "OPTIONS"} and origin and origin != allowed:
            response = JSONResponse(
                {
                    "error": {
                        "code": "ORIGIN_REJECTED",
                        "message": "请求来源无效",
                        "requestId": request_id,
                    }
                },
                status_code=403,
            )
            return await response(scope, receive, send_with_headers)
        await self.app(scope, receive, send_with_headers)

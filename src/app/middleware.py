import logging
from http import HTTPStatus
from time import perf_counter
from uuid import uuid4

from opentelemetry import trace
from starlette.datastructures import URL, Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import AppError, ErrorCode
from app.exception_handlers import error_response
from app.log_events import LogEvent, log_event
from app.settings import runtime_value

logger = logging.getLogger(__name__)


class RequestPolicy:
    """Pure ASGI: do not create a task group and stream adapter for every request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = scope.setdefault("state", {}).setdefault("request_id", str(uuid4()))
        origin = Headers(scope=scope).get("origin")
        url = URL(scope=scope)
        allowed = runtime_value(scope.get("env"), "WELLNEST_ORIGIN", f"{url.scheme}://{url.netloc}")

        response_started = False

        async def send_with_headers(message: Message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                context = trace.get_current_span().get_span_context()
                if context.is_valid:
                    headers["X-Trace-ID"] = format(context.trace_id, "032x")
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        if scope["method"] not in {"GET", "HEAD", "OPTIONS"} and origin and origin != allowed:
            scope["state"]["error_code"] = ErrorCode.origin_rejected
            response = error_response(AppError(ErrorCode.origin_rejected), request_id)
            return await response(scope, receive, send_with_headers)
        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            scope["state"]["error_code"] = ErrorCode.internal_error
            logger.exception("Unhandled request failure")
            if response_started:
                raise
            response = error_response(AppError(ErrorCode.internal_error), request_id)
            await response(scope, receive, send_with_headers)


class RequestSummary:
    """One summary for every HTTP request, including CORS and early rejection."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        state.setdefault("request_id", str(uuid4()))
        started = perf_counter()
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        response_complete = False

        async def observe(message: Message):
            nonlocal status, response_complete
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True

        try:
            await self.app(scope, receive, observe)
        finally:
            route = scope.get("route")
            log_event(
                LogEvent.request_completed,
                request_id=state["request_id"],
                method=scope["method"],
                route=getattr(route, "path", "unmatched"),
                status_code=status,
                duration_ms=round((perf_counter() - started) * 1000, 3),
                response_complete=response_complete,
                error_code=state.get("error_code"),
                error_details=state.get("error_details"),
            )

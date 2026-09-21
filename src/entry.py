from http import HTTPStatus
from urllib.parse import urlsplit

from workers import WorkerEntrypoint, asgi

from app.main import app
from app.worker_runtime import consume_batch, dispatch, safe_relay

PAYMENT_WRITE_PATHS = (
    "/api/payments",
    "/api/mock-",
    "/api/webhooks/payments/",
    "/_internal/payments/consume",
)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        response = await asgi.fetch(app, request, self.env, self.ctx)
        if (
            request.method == "POST"
            and response.status < HTTPStatus.BAD_REQUEST
            and urlsplit(request.url).path.startswith(PAYMENT_WRITE_PATHS)
        ):
            self.ctx.waitUntil(safe_relay(self.env))
        return response

    # workerd currently supplies legacy env/context arguments for event handlers,
    # even though the Python SDK also exposes them on the instance.
    async def queue(self, batch, env=None, ctx=None):
        await consume_batch(batch, self.env)

    async def scheduled(self, controller, env=None, ctx=None):
        await dispatch(self.env, "recover")

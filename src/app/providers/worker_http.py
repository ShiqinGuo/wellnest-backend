"""Keep the mock provider's HTTP and signature boundary over a service binding."""

import asyncio

import httpx


class ServiceBindingTransport(httpx.AsyncBaseTransport):
    def __init__(self, binding, timeout: float):
        self.binding = binding
        self.timeout = timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async with asyncio.timeout(self.timeout):
            body = await request.aread()
            options = {"method": request.method, "headers": dict(request.headers)}
            if body:
                options["body"] = body.decode("utf-8")
            response = await self.binding.fetch(str(request.url), **options)
            content = await response.text()
        return httpx.Response(
            response.status,
            headers=dict(response.headers.items()),
            content=content,
            request=request,
        )

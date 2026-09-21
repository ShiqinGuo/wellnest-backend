"""HTTP contract shared by the merchant adapter and the simulated provider."""

import hashlib
import hmac
import time
from http import HTTPStatus
from typing import Protocol
from uuid import UUID

import httpx

from app.domain.payment import ChannelCreate, ChannelNotification, ChannelPayment
from app.errors import AppError, ErrorCode
from app.payment_settings import PaymentSettings


def sign(body: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(body: bytes, timestamp: str, signature: str, settings: PaymentSettings) -> None:
    try:
        fresh = abs(time.time() - int(timestamp)) <= settings.signature_tolerance
    except ValueError:
        fresh = False
    if (
        not fresh
        or not timestamp.isascii()
        or not signature.isascii()
        or not hmac.compare_digest(
            signature, sign(body, timestamp, settings.webhook_secret.get_secret_value())
        )
    ):
        raise AppError(ErrorCode.invalid_signature)


class PaymentGateway(Protocol):
    async def create(self, command: ChannelCreate) -> ChannelPayment: ...
    async def query(self, merchant_payment_id: UUID) -> ChannelPayment | None: ...
    async def deliver(self, notification: ChannelNotification) -> None: ...


class MockPaymentGateway:
    def __init__(
        self, settings: PaymentSettings, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings
        self.transport = transport

    def client(self):
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=self.settings.network_timeout,
            follow_redirects=False,
        )

    def headers(self):
        return {"Authorization": f"Bearer {self.settings.provider_key.get_secret_value()}"}

    async def create(self, command: ChannelCreate) -> ChannelPayment:
        async with self.client() as client:
            response = await client.post(
                self.settings.provider_url + "/api/mock-provider/payments",
                json=command.model_dump(mode="json"),
                headers=self.headers(),
            )
            response.raise_for_status()
            return ChannelPayment.model_validate(response.json())

    async def query(self, merchant_payment_id: UUID) -> ChannelPayment | None:
        async with self.client() as client:
            response = await client.get(
                self.settings.provider_url + f"/api/mock-provider/payments/{merchant_payment_id}",
                headers=self.headers(),
            )
            if response.status_code == HTTPStatus.NOT_FOUND:
                return None
            response.raise_for_status()
            return ChannelPayment.model_validate(response.json())

    async def deliver(self, notification: ChannelNotification) -> None:
        body = notification.model_dump_json().encode()
        timestamp = str(int(time.time()))
        async with self.client() as client:
            response = await client.post(
                self.settings.merchant_url + "/api/webhooks/payments/mock",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Payment-Timestamp": timestamp,
                    "X-Payment-Signature": sign(
                        body, timestamp, self.settings.webhook_secret.get_secret_value()
                    ),
                },
            )
            response.raise_for_status()

"""Explicit settings shared by API, worker and outbox scheduler."""

import os

from fastapi import Request
from pydantic import BaseModel, Field, SecretStr, model_validator

from app.domain.payment_states import Currency


class PaymentSettings(BaseModel):
    provider_url: str = "http://api:8000"
    public_url: str = "http://localhost:8000"
    merchant_url: str = "http://api:8000"
    provider_key: SecretStr
    webhook_secret: SecretStr
    amount_minor: int = Field(default=990, gt=0)
    currency: Currency = Currency.cny
    network_timeout: float = Field(default=5, gt=0)
    signature_tolerance: int = Field(default=300, gt=0)
    max_webhook_bytes: int = Field(default=16384, gt=0)
    checkout_lifetime: int = Field(default=1800, gt=0)
    reconcile_interval: int = Field(default=30, gt=0)
    refresh_interval: int = Field(default=10, gt=0)
    scheduler_interval: float = Field(default=1, gt=0)
    batch_size: int = Field(default=50, gt=0)
    lease_seconds: int = Field(default=60, gt=0)
    max_attempts: int = Field(default=8, gt=0, le=20)
    retry_base: int = Field(default=2, gt=0, le=10)
    retry_cap: int = Field(default=300, gt=0)
    execution_timeout: int = Field(default=25, gt=0)
    relay_timeout: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def validate_deadlines(self):
        if not self.execution_timeout < self.lease_seconds:
            raise ValueError("Require execution timeout < lease")
        return self


def load_payment_settings(env=None) -> PaymentSettings:
    values = {}
    for name in PaymentSettings.model_fields:
        key = f"WELLNEST_PAYMENT_{name.upper()}"
        value = getattr(env, key, None) if env is not None else os.getenv(key)
        if value is not None:
            values[name] = value
    return PaymentSettings.model_validate(values)


async def payment_settings(request: Request) -> PaymentSettings:
    return load_payment_settings(request.scope.get("env"))

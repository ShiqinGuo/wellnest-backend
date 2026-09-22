"""Typed persistence records. Driver records and JSON decoding stop at this boundary."""

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg
from pydantic import TypeAdapter

from app.domain.enums import PlanId
from app.domain.payment_states import (
    Currency,
    InboxStatus,
    OutboxStatus,
    PaymentProvider,
    PaymentStatus,
    PaymentTask,
)


@dataclass(frozen=True, slots=True)
class PaymentRow:
    id: UUID
    user_id: UUID
    plan_id: PlanId
    status: PaymentStatus
    amount_minor: int
    currency: Currency
    provider: PaymentProvider
    provider_transaction_id: UUID | None
    checkout_url: str | None
    created_at: datetime
    updated_at: datetime
    next_check_at: datetime
    last_refresh_at: datetime | None


@dataclass(frozen=True, slots=True)
class OutboxRow:
    id: UUID
    task: PaymentTask
    aggregate_id: UUID
    status: OutboxStatus
    attempts: int
    available_at: datetime
    headers: dict[str, str]
    lease_token: UUID | None
    lease_until: datetime | None
    processed_at: datetime | None
    last_error: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WebhookRow:
    id: UUID
    payment_id: UUID
    status: InboxStatus
    payload: str
    fingerprint: str
    rejection_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderRow:
    id: UUID
    merchant_payment_id: UUID
    amount_minor: int
    currency: Currency
    status: PaymentStatus
    checkout_token: str
    event_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


PAYMENT_ROW = TypeAdapter(PaymentRow)
OUTBOX_ROW = TypeAdapter(OutboxRow)
WEBHOOK_ROW = TypeAdapter(WebhookRow)
PROVIDER_ROW = TypeAdapter(ProviderRow)


def optional_row[T](row: asyncpg.Record | None, adapter: TypeAdapter[T]) -> T | None:
    if row is None:
        return None
    values = dict(row)
    if "headers" in values:
        values["headers"] = json.loads(values["headers"])
    return adapter.validate_python(values)


def required_row[T](row: asyncpg.Record | None, adapter: TypeAdapter[T]) -> T:
    result = optional_row(row, adapter)
    if result is None:
        raise LookupError("Expected database row is missing")
    return result

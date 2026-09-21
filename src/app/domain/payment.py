from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import PlanId
from app.domain.payment_states import Currency, NextAction, PaymentProvider, PaymentStatus


class PayCommand(BaseModel):
    plan_id: PlanId = PlanId.demo


class PaymentData(BaseModel):
    id: UUID
    user_id: UUID
    plan_id: PlanId
    status: PaymentStatus
    amount_minor: int
    currency: Currency
    provider: PaymentProvider
    provider_transaction_id: UUID | None = None
    checkout_url: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def next_action(self) -> NextAction:
        if self.status != PaymentStatus.pending:
            return NextAction.none
        return NextAction.open_checkout if self.checkout_url else NextAction.wait


class ChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_payment_id: UUID
    amount_minor: int = Field(gt=0, strict=True)
    currency: Currency


class ChannelPayment(ChannelCreate):
    transaction_id: UUID
    status: PaymentStatus
    checkout_url: str
    expires_at: datetime


class ChannelNotification(ChannelPayment):
    event_id: UUID


class CheckoutConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal[PaymentStatus.succeeded, PaymentStatus.failed] = PaymentStatus.succeeded

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.domain.enums import PlanId
from app.domain.payment import PayCommand, PaymentData
from app.domain.payment_states import Currency, NextAction, PaymentStatus
from app.schemas.base import APIModel


class PayInput(APIModel):
    plan_id: PlanId = PlanId.demo

    def to_command(self) -> PayCommand:
        return PayCommand.model_validate(self.model_dump(exclude_unset=True))


class PaymentView(APIModel):
    id: UUID
    plan_id: PlanId
    status: PaymentStatus
    amount_minor: int
    currency: Currency
    checkout_url: str | None
    next_action: NextAction
    simulated: Literal[True] = True
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_data(cls, data: PaymentData):
        return cls(**{k: getattr(data, k) for k in cls.model_fields if k != "simulated"})


class Accepted(APIModel):
    accepted: Literal[True] = True

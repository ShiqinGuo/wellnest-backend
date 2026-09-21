from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PaymentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event_id: UUID
    lease_token: UUID


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry_after: int | None = Field(default=None, gt=0)

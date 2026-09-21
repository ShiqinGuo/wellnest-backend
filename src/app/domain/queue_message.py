from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class PaymentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event_id: UUID
    lease_token: UUID
    headers: dict[str, str] = Field(default_factory=dict)

    published_at: AwareDatetime | None = None


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry_after: int | None = Field(default=None, gt=0)

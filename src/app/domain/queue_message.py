from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class PaymentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event_id: UUID
    lease_token: UUID
    traceparent: str | None = Field(
        default=None, pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
    )
    published_at: AwareDatetime | None = None


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry_after: int | None = Field(default=None, gt=0)

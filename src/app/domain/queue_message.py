from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event_id: UUID
    lease_token: UUID

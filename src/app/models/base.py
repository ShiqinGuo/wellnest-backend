from datetime import datetime
from typing import Annotated
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import (
    Activity,
    AssessmentStatus,
    Barrier,
    DailyActivity,
    Energy,
    Experience,
    Goal,
    MealRhythm,
    PlanId,
    Sex,
    Sleep,
    Step,
    TimeWindow,
)
from app.domain.payment_states import (
    Currency,
    InboxStatus,
    OutboxStatus,
    PaymentProvider,
    PaymentStatus,
    PaymentTask,
)

UuidPk = Annotated[UUID, mapped_column(primary_key=True)]
UserFk = Annotated[UUID, mapped_column(ForeignKey("users.id", ondelete="CASCADE"))]
Str16 = Annotated[str, mapped_column(String(16))]
Str24 = Annotated[str, mapped_column(String(24))]
Str32 = Annotated[str, mapped_column(String(32))]
Str64 = Annotated[str, mapped_column(String(64))]
Str128 = Annotated[str, mapped_column(String(128))]
Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]
CreatedAt = Annotated[datetime, mapped_column(DateTime(timezone=True), server_default=func.now())]
JsonObject = Annotated[dict[str, object], mapped_column(JSONB)]


class Base(DeclarativeBase):
    type_annotation_map = {
        enum: Enum(
            enum,
            native_enum=False,
            create_constraint=False,
            length=length,
            values_callable=lambda cls: [member.value for member in cls],
        )
        for enum, length in (
            (PaymentStatus, 16),
            (PaymentProvider, 16),
            (Currency, 3),
            (OutboxStatus, 16),
            (InboxStatus, 16),
            (PaymentTask, 40),
            (AssessmentStatus, 16),
            (Sex, 16),
            (Goal, 16),
            (Activity, 16),
            (Step, 32),
            (PlanId, 32),
            (Experience, 32),
            (DailyActivity, 32),
            (Sleep, 32),
            (Energy, 32),
            (MealRhythm, 32),
            (Barrier, 32),
            (TimeWindow, 32),
        )
    }


class CreatedAtMixin:
    created_at: Mapped[CreatedAt]


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[CreatedAt]

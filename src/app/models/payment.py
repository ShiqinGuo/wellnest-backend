from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import PlanId
from app.models.base import Base, CreatedAt, CreatedAtMixin, UserFk, UuidPk


class Subscription(Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[UserFk] = mapped_column(primary_key=True)
    plan_id: Mapped[PlanId] = mapped_column()
    activated_at: Mapped[CreatedAt]
    source_payment_id: Mapped[UUID | None] = mapped_column(ForeignKey("payments.id"), unique=True)

    __table_args__ = (CheckConstraint(plan_id == PlanId.demo.value, name="subscription_plan"),)


class MockPayment(CreatedAtMixin, Base):
    __tablename__ = "mock_payments"

    id: Mapped[UuidPk]
    user_id: Mapped[UserFk] = mapped_column(unique=True)
    plan_id: Mapped[PlanId] = mapped_column()

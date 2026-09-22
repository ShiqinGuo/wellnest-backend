from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import PlanId
from app.domain.payment_states import (
    Currency,
    InboxStatus,
    OutboxStatus,
    PaymentProvider,
    PaymentStatus,
    PaymentTask,
)
from app.models.base import (
    Base,
    CreatedAtMixin,
    JsonObject,
    Str64,
    Timestamp,
    TimestampMixin,
    UserFk,
    UuidPk,
)


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    id: Mapped[UuidPk] = mapped_column()
    user_id: Mapped[UserFk] = mapped_column()
    plan_id: Mapped[PlanId] = mapped_column()
    status: Mapped[PaymentStatus] = mapped_column()
    amount_minor: Mapped[int] = mapped_column()
    currency: Mapped[Currency] = mapped_column()
    provider: Mapped[PaymentProvider] = mapped_column()
    provider_transaction_id: Mapped[UUID | None] = mapped_column(unique=True)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    next_check_at: Mapped[Timestamp] = mapped_column()
    last_refresh_at: Mapped[Timestamp | None] = mapped_column()
    __table_args__ = (
        CheckConstraint(amount_minor > 0, name="payment_amount_positive"),
        CheckConstraint(status.in_([v.value for v in PaymentStatus]), name="payment_status"),
        CheckConstraint(currency.in_([v.value for v in Currency]), name="payment_currency"),
        CheckConstraint(provider.in_([v.value for v in PaymentProvider]), name="payment_provider"),
        Index(
            "payment_one_pending",
            user_id,
            plan_id,
            unique=True,
            postgresql_where=status == PaymentStatus.pending.value,
        ),
        Index("payment_due", next_check_at, postgresql_where=status == PaymentStatus.pending.value),
    )


class PaymentWebhook(CreatedAtMixin, Base):
    __tablename__ = "payment_webhook_inbox"
    id: Mapped[UuidPk] = mapped_column()
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id"))
    status: Mapped[InboxStatus] = mapped_column()
    payload: Mapped[JsonObject] = mapped_column()
    fingerprint: Mapped[Str64] = mapped_column()
    rejection_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        CheckConstraint(status.in_([v.value for v in InboxStatus]), name="webhook_status"),
    )


class Outbox(CreatedAtMixin, Base):
    __tablename__ = "outbox_events"
    id: Mapped[UuidPk] = mapped_column()
    task: Mapped[PaymentTask] = mapped_column()
    aggregate_id: Mapped[UUID] = mapped_column()
    status: Mapped[OutboxStatus] = mapped_column()
    attempts: Mapped[int] = mapped_column(server_default="0")
    available_at: Mapped[Timestamp] = mapped_column()
    headers: Mapped[JsonObject] = mapped_column(server_default="{}")
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[Timestamp | None] = mapped_column()
    processed_at: Mapped[Timestamp | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        CheckConstraint(status.in_([v.value for v in OutboxStatus]), name="outbox_status"),
        CheckConstraint(task.in_([v.value for v in PaymentTask]), name="outbox_task"),
        CheckConstraint(attempts >= 0, name="outbox_attempts"),
        Index("outbox_due", available_at, postgresql_where=processed_at.is_(None)),
        Index(
            "outbox_one_open_task",
            task,
            aggregate_id,
            unique=True,
            postgresql_where=processed_at.is_(None) & (status != OutboxStatus.failed.value),
        ),
    )


class MockProviderPayment(TimestampMixin, Base):
    """Provider-owned records deliberately have no merchant-table foreign keys."""

    __tablename__ = "mock_provider_payments"
    id: Mapped[UuidPk] = mapped_column()
    merchant_payment_id: Mapped[UUID] = mapped_column(unique=True)
    amount_minor: Mapped[int] = mapped_column()
    currency: Mapped[Currency] = mapped_column()
    status: Mapped[PaymentStatus] = mapped_column()
    checkout_token: Mapped[Str64] = mapped_column(unique=True)
    event_id: Mapped[UUID] = mapped_column(unique=True)
    expires_at: Mapped[Timestamp] = mapped_column()
    __table_args__ = (
        CheckConstraint(amount_minor > 0, name="mock_provider_amount"),
        CheckConstraint(currency.in_([v.value for v in Currency]), name="mock_provider_currency"),
        CheckConstraint(status.in_([v.value for v in PaymentStatus]), name="mock_provider_status"),
    )

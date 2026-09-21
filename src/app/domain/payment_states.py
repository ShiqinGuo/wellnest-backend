"""Independent state machines for payments and delivery infrastructure."""

from enum import StrEnum

from app.errors import AppError, ErrorCode


class PaymentStatus(StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    closed = "closed"


class PaymentEvent(StrEnum):
    succeed = "succeed"
    fail = "fail"
    close = "close"


class PaymentStateMachine:
    targets = {
        PaymentEvent.succeed: PaymentStatus.succeeded,
        PaymentEvent.fail: PaymentStatus.failed,
        PaymentEvent.close: PaymentStatus.closed,
    }

    @classmethod
    def transition(cls, state: PaymentStatus, event: PaymentEvent) -> PaymentStatus:
        target = cls.targets[event]
        if state not in (PaymentStatus.pending, target):
            raise AppError(ErrorCode.payment_conflict)
        return target


class NextAction(StrEnum):
    wait = "wait"
    open_checkout = "open_checkout"
    none = "none"


class OutboxStatus(StrEnum):
    pending = "pending"
    published = "published"
    failed = "failed"


class OutboxEvent(StrEnum):
    publish = "publish"
    retry = "retry"
    exhaust = "exhaust"
    requeue = "requeue"


class OutboxStateMachine:
    transitions = {
        (OutboxStatus.pending, OutboxEvent.publish): OutboxStatus.published,
        (OutboxStatus.published, OutboxEvent.publish): OutboxStatus.published,
        (OutboxStatus.pending, OutboxEvent.retry): OutboxStatus.pending,
        (OutboxStatus.published, OutboxEvent.retry): OutboxStatus.pending,
        (OutboxStatus.pending, OutboxEvent.exhaust): OutboxStatus.failed,
        (OutboxStatus.published, OutboxEvent.exhaust): OutboxStatus.failed,
        (OutboxStatus.failed, OutboxEvent.requeue): OutboxStatus.pending,
    }

    @classmethod
    def transition(cls, state: OutboxStatus, event: OutboxEvent) -> OutboxStatus:
        return cls.transitions[(state, event)]


class InboxStatus(StrEnum):
    pending = "pending"
    processed = "processed"
    rejected = "rejected"


class InboxEvent(StrEnum):
    accept = "accept"
    reject = "reject"


class InboxStateMachine:
    @staticmethod
    def transition(state: InboxStatus, event: InboxEvent) -> InboxStatus:
        target = InboxStatus.processed if event == InboxEvent.accept else InboxStatus.rejected
        if state not in (InboxStatus.pending, target):
            raise ValueError("Inbox outcome is immutable")
        return target


class PaymentTask(StrEnum):
    create = "payment.create"
    reconcile = "payment.reconcile"
    process_webhook = "payment.process_webhook"
    deliver_webhook = "mock.deliver_webhook"


class PaymentProvider(StrEnum):
    mock = "mock"


class Currency(StrEnum):
    cny = "CNY"

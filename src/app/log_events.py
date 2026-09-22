"""Structured events, correlated by the shared formatter and emitted after commit."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum


class LogEvent(StrEnum):
    request_completed = "request.completed"
    assessment_completed = "assessment.completed"
    command_committed = "command.committed"
    payment_created = "payment.created"
    provider_confirmed = "payment.provider_confirmed"
    webhook_received = "payment.webhook_received"
    webhook_processed = "payment.webhook_processed"
    payment_transitioned = "payment.transitioned"
    subscription_activated = "subscription.activated"


logger = logging.getLogger(__name__)
_pending: ContextVar[list[tuple[LogEvent, dict[str, object]]] | None] = ContextVar(
    "pending_log_events", default=None
)


def log_event(event: LogEvent, **fields: object) -> None:
    try:
        logger.info(event.value, extra={"event_fields": {**fields, "event": event.value}})
    except Exception:
        # A failed log sink must not change an already committed business outcome.
        pass


def business_event(event: LogEvent, **fields: object) -> None:
    pending = _pending.get()
    if pending is None:
        raise RuntimeError("Business events require an active transaction")
    pending.append((event, fields))


@contextmanager
def committed_events() -> Iterator[None]:
    pending: list[tuple[LogEvent, dict[str, object]]] = []
    token = _pending.set(pending)
    try:
        yield
    except BaseException:
        raise
    else:
        for event, fields in pending:
            log_event(event, **fields)
    finally:
        _pending.reset(token)

from enum import StrEnum
from http import HTTPStatus


class ErrorCode(StrEnum):
    """Public error contract: one code, HTTP status and default message per error."""

    def __new__(cls, code: str, status: HTTPStatus, message: str):
        member = str.__new__(cls, code)
        member._value_ = code
        member.status = status
        member.message = message
        return member

    internal_error = ("INTERNAL_ERROR", HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")
    payment_conflict = (
        "PAYMENT_CONFLICT",
        HTTPStatus.CONFLICT,
        "Conflicting payment state or event",
    )
    payment_mismatch = (
        "PAYMENT_MISMATCH",
        HTTPStatus.CONFLICT,
        "Payment identity or amount mismatch",
    )
    invalid_signature = ("INVALID_SIGNATURE", HTTPStatus.UNAUTHORIZED, "Invalid webhook signature")
    invalid_provider_key = (
        "INVALID_PROVIDER_KEY",
        HTTPStatus.UNAUTHORIZED,
        "Invalid provider credentials",
    )
    already_subscribed = ("ALREADY_SUBSCRIBED", HTTPStatus.CONFLICT, "Membership is already active")
    checkout_expired = ("CHECKOUT_EXPIRED", HTTPStatus.CONFLICT, "Checkout has expired")
    guidance_not_retryable = (
        "GUIDANCE_NOT_RETRYABLE",
        HTTPStatus.CONFLICT,
        "Guidance cannot be retried in its current state",
    )
    membership_required = ("MEMBERSHIP_REQUIRED", HTTPStatus.FORBIDDEN, "Membership is required")
    unsupported_flow = ("UNSUPPORTED_FLOW", HTTPStatus.CONFLICT, "Unsupported assessment flow")
    assessment_completed = (
        "ASSESSMENT_COMPLETED",
        HTTPStatus.CONFLICT,
        "Assessment is already completed",
    )
    assessment_required = (
        "ASSESSMENT_REQUIRED",
        HTTPStatus.CONFLICT,
        "Complete an assessment first",
    )
    idempotency_conflict = (
        "IDEMPOTENCY_CONFLICT",
        HTTPStatus.CONFLICT,
        "Idempotency key was already used with different content",
    )
    incomplete_assessment = (
        "INCOMPLETE_ASSESSMENT",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Required assessment fields are missing",
    )
    invalid_answers = (
        "INVALID_ANSWERS",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Invalid assessment answers",
    )
    invalid_command_key = (
        "INVALID_COMMAND_KEY",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Invalid idempotency key",
    )
    invalid_source = (
        "INVALID_SOURCE",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Invalid source assessment",
    )
    not_found = ("NOT_FOUND", HTTPStatus.NOT_FOUND, "Requested resource was not found")
    result_not_found = (
        "RESULT_NOT_FOUND",
        HTTPStatus.NOT_FOUND,
        "Assessment result is unavailable",
    )
    session_expired = ("SESSION_EXPIRED", HTTPStatus.UNAUTHORIZED, "Session has expired")
    session_required = ("SESSION_REQUIRED", HTTPStatus.UNAUTHORIZED, "A session is required")
    step_unavailable = (
        "STEP_UNAVAILABLE",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Complete the required steps before continuing",
    )
    subscription_inconsistent = (
        "SUBSCRIPTION_INCONSISTENT",
        HTTPStatus.CONFLICT,
        "Subscription state is inconsistent",
    )
    unsupported_estimate = (
        "UNSUPPORTED_ESTIMATE",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Assessment inputs do not support an estimate",
    )
    version_conflict = (
        "VERSION_CONFLICT",
        HTTPStatus.CONFLICT,
        "Resource has changed; reload before retrying",
    )
    origin_rejected = ("ORIGIN_REJECTED", HTTPStatus.FORBIDDEN, "Request origin is not allowed")
    validation_error = (
        "VALIDATION_ERROR",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Invalid request data",
    )
    invalid_internal_key = (
        "INVALID_INTERNAL_KEY",
        HTTPStatus.UNAUTHORIZED,
        "Invalid internal credentials",
    )
    webhook_too_large = (
        "WEBHOOK_TOO_LARGE",
        HTTPStatus.CONTENT_TOO_LARGE,
        "Webhook body exceeds the size limit",
    )
    invalid_notification = (
        "INVALID_NOTIFICATION",
        HTTPStatus.UNPROCESSABLE_CONTENT,
        "Invalid channel notification",
    )


class AppError(Exception):
    def __init__(self, code: ErrorCode, *, details: dict[str, object] | None = None):
        self.code = code
        self.message = code.message
        self.status = code.status
        self.details = details or {}
        super().__init__(self.message)

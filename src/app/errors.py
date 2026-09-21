from enum import StrEnum
from http import HTTPStatus


class ErrorCode(StrEnum):
    internal_error = "INTERNAL_ERROR"
    payment_conflict = "PAYMENT_CONFLICT"
    payment_mismatch = "PAYMENT_MISMATCH"
    invalid_signature = "INVALID_SIGNATURE"
    invalid_provider_key = "INVALID_PROVIDER_KEY"
    already_subscribed = "ALREADY_SUBSCRIBED"
    checkout_expired = "CHECKOUT_EXPIRED"
    guidance_not_retryable = "GUIDANCE_NOT_RETRYABLE"
    membership_required = "MEMBERSHIP_REQUIRED"
    unsupported_flow = "UNSUPPORTED_FLOW"
    assessment_completed = "ASSESSMENT_COMPLETED"
    assessment_required = "ASSESSMENT_REQUIRED"
    idempotency_conflict = "IDEMPOTENCY_CONFLICT"
    incomplete_assessment = "INCOMPLETE_ASSESSMENT"
    invalid_answers = "INVALID_ANSWERS"
    invalid_command_key = "INVALID_COMMAND_KEY"
    invalid_source = "INVALID_SOURCE"
    not_found = "NOT_FOUND"
    result_not_found = "RESULT_NOT_FOUND"
    session_expired = "SESSION_EXPIRED"
    session_required = "SESSION_REQUIRED"
    step_unavailable = "STEP_UNAVAILABLE"
    subscription_inconsistent = "SUBSCRIPTION_INCONSISTENT"
    unsupported_estimate = "UNSUPPORTED_ESTIMATE"
    version_conflict = "VERSION_CONFLICT"


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status: int = HTTPStatus.CONFLICT,
        details: dict[str, object] | None = None,
    ):
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}
        super().__init__(message)

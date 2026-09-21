from types import MappingProxyType

from app.domain.enums import (
    AssessmentEvent,
    AssessmentStatus,
    GuidanceEvent,
    GuidanceStatus,
    SubscriptionEvent,
    SubscriptionStatus,
)
from app.errors import AppError, ErrorCode


class AssessmentStateMachine:
    transitions = MappingProxyType(
        {
            (AssessmentStatus.draft, AssessmentEvent.edit): AssessmentStatus.draft,
            (AssessmentStatus.draft, AssessmentEvent.submit): AssessmentStatus.completed,
            (AssessmentStatus.completed, AssessmentEvent.submit): AssessmentStatus.completed,
        }
    )

    @classmethod
    def transition(cls, state: AssessmentStatus, event: AssessmentEvent) -> AssessmentStatus:
        target = cls.transitions.get((state, event))
        if target is None:
            raise AppError(ErrorCode.assessment_completed)
        return target


class SubscriptionStateMachine:
    transitions = MappingProxyType(
        {
            (SubscriptionStatus.inactive, SubscriptionEvent.activate): SubscriptionStatus.active,
            (SubscriptionStatus.active, SubscriptionEvent.activate): SubscriptionStatus.active,
        }
    )

    @classmethod
    def transition(cls, state: SubscriptionStatus, event: SubscriptionEvent) -> SubscriptionStatus:
        return cls.transitions[(state, event)]


class GuidanceStateMachine:
    """Retry permission belongs to guidance, independently of assessment/subscription."""

    retryable = frozenset({GuidanceStatus.unavailable, GuidanceStatus.uncertain})
    transitions = MappingProxyType(
        {
            (state, GuidanceEvent.retry, outcome): outcome
            for state in retryable
            for outcome in GuidanceStatus
        }
    )

    @classmethod
    def check(cls, state: GuidanceStatus, event: GuidanceEvent) -> None:
        if event != GuidanceEvent.retry or state not in cls.retryable:
            raise AppError(ErrorCode.guidance_not_retryable)

    @classmethod
    def transition(
        cls, state: GuidanceStatus, event: GuidanceEvent, outcome: GuidanceStatus
    ) -> GuidanceStatus:
        cls.check(state, event)
        return cls.transitions[(state, event, outcome)]

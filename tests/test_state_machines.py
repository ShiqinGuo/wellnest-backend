import pytest

from app.domain.assessment import Answers
from app.domain.enums import (
    AssessmentEvent,
    AssessmentStatus,
    Step,
    SubscriptionEvent,
    SubscriptionStatus,
)
from app.domain.flow import AssessmentNavigation
from app.domain.state_machine import AssessmentStateMachine, SubscriptionStateMachine
from app.errors import AppError


@pytest.mark.parametrize(
    "state,event,target",
    [
        (AssessmentStatus.draft, AssessmentEvent.edit, AssessmentStatus.draft),
        (AssessmentStatus.draft, AssessmentEvent.submit, AssessmentStatus.completed),
        (AssessmentStatus.completed, AssessmentEvent.submit, AssessmentStatus.completed),
    ],
)
def test_assessment_transitions(state, event, target):
    assert AssessmentStateMachine.transition(state, event) == target


def test_completed_assessment_rejects_edit():
    with pytest.raises(AppError, match="已完成"):
        AssessmentStateMachine.transition(AssessmentStatus.completed, AssessmentEvent.edit)


@pytest.mark.parametrize("state", list(SubscriptionStatus))
def test_subscription_activation_is_idempotent(state):
    assert (
        SubscriptionStateMachine.transition(state, SubscriptionEvent.activate)
        == SubscriptionStatus.active
    )


def test_navigation_guards_are_separate_from_lifecycle():
    answers = Answers(sex="female")
    assert AssessmentNavigation.transition(Step.sex, Step.goal, answers) == Step.goal
    assert AssessmentNavigation.transition(Step.goal, Step.sex, answers) == Step.sex
    with pytest.raises(AppError, match="必填"):
        AssessmentNavigation.transition(Step.sex, Step.review, answers)
    with pytest.raises(AppError, match="查看结果"):
        AssessmentNavigation.transition(Step.sex, Step.result, answers)
    assert AssessmentNavigation.reconcile(Step.review, answers) == Step.goal

from app.domain.assessment import Answers
from app.domain.enums import Barrier, FlowVersion, Goal, Step
from app.errors import AppError, ErrorCode

STEPS = (
    Step.welcome,
    Step.sex,
    Step.goal,
    Step.age,
    Step.height,
    Step.weight,
    Step.target,
    Step.activity,
    Step.review,
)
GUIDED_STEPS = (
    Step.welcome,
    Step.goal,
    Step.goal_feedback,
    Step.sex,
    Step.activity,
    Step.activity_feedback,
    Step.age,
    Step.height,
    Step.weight,
    Step.target,
    Step.target_feedback,
    Step.review,
)
LIFESTYLE_STEPS = (
    Step.welcome,
    Step.goal,
    Step.goal_feedback,
    Step.sex,
    Step.secondary_goals,
    Step.experience,
    Step.activity,
    Step.daily_activity,
    Step.limitations,
    Step.movement_feedback,
    Step.sleep,
    Step.energy,
    Step.meal_rhythm,
    Step.food_habits,
    Step.barrier,
    Step.time_window,
    Step.habits_feedback,
    Step.age,
    Step.height,
    Step.weight,
    Step.target,
    Step.target_feedback,
    Step.review,
)
FLOW_STEPS = {
    FlowVersion.legacy: STEPS,
    FlowVersion.guided: GUIDED_STEPS,
    FlowVersion.lifestyle: LIFESTYLE_STEPS,
}
FIELD_FOR_STEP = {
    Step.sex: "sex",
    Step.goal: "goal",
    Step.age: "age",
    Step.height: "height_cm",
    Step.weight: "weight_kg",
    Step.target: "target_weight_kg",
    Step.activity: "activity",
    Step.secondary_goals: "secondary_goals",
    Step.experience: "experience",
    Step.daily_activity: "daily_activity",
    Step.limitations: "limitations",
    Step.sleep: "sleep",
    Step.energy: "energy",
    Step.meal_rhythm: "meal_rhythm",
    Step.food_habits: "food_habits",
    Step.barrier: "barrier",
    Step.time_window: "time_window",
}


def applicable_steps(answers: Answers, flow_version: str):
    return tuple(
        step
        for step in FLOW_STEPS.get(flow_version, STEPS)
        if not (step == Step.target and answers.goal == Goal.maintain)
        and not (step == Step.time_window and answers.barrier != Barrier.time)
    )


class AssessmentNavigation:
    """Quiz navigation is independent of the assessment's draft/completed lifecycle."""

    @staticmethod
    def transition(
        current: Step,
        target: Step,
        answers: Answers,
        flow_version: str = FlowVersion.legacy,
    ) -> Step:
        steps = applicable_steps(answers, flow_version)
        if current not in FLOW_STEPS[flow_version] or target not in steps:
            raise AppError(ErrorCode.step_unavailable)
        for prior in steps[: steps.index(target)]:
            field = FIELD_FOR_STEP.get(prior)
            if field and getattr(answers, field) is None:
                raise AppError(ErrorCode.step_unavailable, details={"stepId": prior})
        return target

    @staticmethod
    def reconcile(
        current: Step,
        answers: Answers,
        flow_version: str = FlowVersion.legacy,
    ) -> Step:
        steps = applicable_steps(answers, flow_version)
        if current not in steps:
            current = Step.habits_feedback if current == Step.time_window else Step.target_feedback
        for prior in steps[: steps.index(current)]:
            field = FIELD_FOR_STEP.get(prior)
            if field and getattr(answers, field) is None:
                return prior
        return current

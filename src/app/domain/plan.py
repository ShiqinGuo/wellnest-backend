"""Language-neutral lifestyle decisions; wording belongs to the client."""

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    Activity,
    Barrier,
    DailyActivity,
    Energy,
    Experience,
    FoodHabit,
    Limitation,
    MealRhythm,
    SecondaryGoal,
    Sleep,
    TimeWindow,
)

if TYPE_CHECKING:
    from app.domain.assessment import Answers


class PlanRuleVersion(StrEnum):
    lifestyle_v1 = "lifestyle-plan-v1"


class PlanTopic(StrEnum):
    movement = "movement"
    recovery = "recovery"
    meals = "meals"
    consistency = "consistency"


class PlanCode(StrEnum):
    movement_title = "movement_title"
    recovery_title = "recovery_title"
    meals_title = "meals_title"
    consistency_title = "consistency_title"
    experience = "experience"
    activity = "activity"
    seated = "seated"
    on_feet = "on_feet"
    movement_break = "movement_break"
    observe_activity = "observe_activity"
    familiar_activity = "familiar_activity"
    gentle_movement = "gentle_movement"
    familiar_strength = "familiar_strength"
    seek_advice = "seek_advice"
    limitation_boundary = "limitation_boundary"
    sleep_energy = "sleep_energy"
    record_sleep = "record_sleep"
    keep_sleep = "keep_sleep"
    meal_habits = "meal_habits"
    protect_meal = "protect_meal"
    unsweetened_drink = "unsweetened_drink"
    record_snack = "record_snack"
    record_sweets = "record_sweets"
    keep_meals = "keep_meals"
    barrier = "barrier"
    pair_action = "pair_action"
    record_action = "record_action"
    try_easiest = "try_easiest"
    review_routine = "review_routine"
    schedule_action = "schedule_action"
    preference = "preference"


class PlanParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experience: Experience | None = None
    activity: Activity | None = None
    sleep: Sleep | None = None
    energy: Energy | None = None
    meal_rhythm: MealRhythm | None = None
    food_habits: list[FoodHabit] | None = None
    barrier: Barrier | None = None
    time_window: TimeWindow | None = None
    limitations: list[Limitation] | None = None
    preference: SecondaryGoal | None = None


class PlanMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: PlanCode
    params: PlanParams = Field(default_factory=PlanParams)

    @model_validator(mode="after")
    def validate_parameters(self):
        required = {
            PlanCode.experience: {"experience"},
            PlanCode.activity: {"activity"},
            PlanCode.sleep_energy: {"sleep", "energy"},
            PlanCode.meal_habits: {"meal_rhythm", "food_habits"},
            PlanCode.barrier: {"barrier"},
            PlanCode.schedule_action: {"time_window"},
            PlanCode.preference: {"preference"},
            PlanCode.limitation_boundary: {"limitations"},
        }.get(self.code, set())
        supplied = self.params.model_dump(exclude_none=True)
        if supplied.keys() != required or any(value == [] for value in supplied.values()):
            raise ValueError("Plan message parameters do not match its code")
        return self


class PlanCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: PlanTopic
    title: PlanMessage
    reason: list[PlanMessage]
    action: list[PlanMessage]
    source_fields: list[str]


class PlanPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[2] = 2
    rules_version: PlanRuleVersion = PlanRuleVersion.lifestyle_v1
    cards: list[PlanCard]
    preferences: list[PlanMessage]
    boundaries: list[PlanMessage]


def message(code: PlanCode, **params) -> PlanMessage:
    return PlanMessage(code=code, params=PlanParams(**params))


def build_plan(answers: "Answers") -> PlanPreview | None:
    if answers.experience is None:
        return None
    reason = [message(PlanCode.experience, experience=answers.experience)]
    if answers.activity is not None:
        reason.append(message(PlanCode.activity, activity=answers.activity))
    if answers.daily_activity == DailyActivity.seated:
        reason.append(message(PlanCode.seated))
        action = [message(PlanCode.movement_break)]
    elif answers.daily_activity == DailyActivity.on_feet:
        reason.append(message(PlanCode.on_feet))
        action = [message(PlanCode.observe_activity)]
    else:
        action = [message(PlanCode.familiar_activity)]
    if SecondaryGoal.mobility in (answers.secondary_goals or []):
        action.append(message(PlanCode.gentle_movement))
    elif SecondaryGoal.strength in (answers.secondary_goals or []):
        action.append(message(PlanCode.familiar_strength))
    boundaries = []
    if answers.limitations and Limitation.none not in answers.limitations:
        boundaries.append(message(PlanCode.limitation_boundary, limitations=answers.limitations))
        action = [message(PlanCode.seek_advice)]
    cards = [
        PlanCard(
            topic=PlanTopic.movement,
            title=message(PlanCode.movement_title),
            reason=reason,
            action=action,
            source_fields=[
                "secondaryGoals",
                "experience",
                "activity",
                "dailyActivity",
                "limitations",
            ],
        )
    ]
    if answers.sleep is not None and answers.energy is not None:
        code = (
            PlanCode.keep_sleep
            if answers.sleep == Sleep.rested and answers.energy == Energy.steady
            else PlanCode.record_sleep
        )
        cards.append(
            PlanCard(
                topic=PlanTopic.recovery,
                title=message(PlanCode.recovery_title),
                reason=[message(PlanCode.sleep_energy, sleep=answers.sleep, energy=answers.energy)],
                action=[message(code)],
                source_fields=["sleep", "energy"],
            )
        )
    if answers.meal_rhythm is not None and answers.food_habits is not None:
        if answers.meal_rhythm != MealRhythm.regular_meals:
            code = PlanCode.protect_meal
        elif FoodHabit.sweet_drinks in answers.food_habits:
            code = PlanCode.unsweetened_drink
        elif FoodHabit.late_snacks in answers.food_habits:
            code = PlanCode.record_snack
        elif FoodHabit.sweets in answers.food_habits:
            code = PlanCode.record_sweets
        else:
            code = PlanCode.keep_meals
        cards.append(
            PlanCard(
                topic=PlanTopic.meals,
                title=message(PlanCode.meals_title),
                reason=[
                    message(
                        PlanCode.meal_habits,
                        meal_rhythm=answers.meal_rhythm,
                        food_habits=answers.food_habits,
                    )
                ],
                action=[message(code)],
                source_fields=["mealRhythm", "foodHabits"],
            )
        )
    if answers.barrier is not None:
        actions = {
            Barrier.time: PlanCode.pair_action,
            Barrier.motivation: PlanCode.record_action,
            Barrier.unsure: PlanCode.try_easiest,
            Barrier.no_barrier: PlanCode.review_routine,
        }
        action_message = (
            message(PlanCode.schedule_action, time_window=answers.time_window)
            if answers.barrier == Barrier.time and answers.time_window
            else message(actions[answers.barrier])
        )
        cards.append(
            PlanCard(
                topic=PlanTopic.consistency,
                title=message(PlanCode.consistency_title),
                reason=[message(PlanCode.barrier, barrier=answers.barrier)],
                action=[action_message],
                source_fields=["barrier", "timeWindow"]
                if answers.barrier == Barrier.time
                else ["barrier"],
            )
        )
    return PlanPreview(
        cards=cards,
        preferences=[
            message(PlanCode.preference, preference=g) for g in answers.secondary_goals or []
        ],
        boundaries=boundaries,
    )

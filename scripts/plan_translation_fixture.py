"""Exercise real plan output variants for the frontend localization contract test."""

import json
import sys
from datetime import date
from itertools import combinations, product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.domain.assessment import Answers, CompleteAnswers  # noqa: E402
from app.domain.calculation import assess  # noqa: E402
from app.domain.enums import (  # noqa: E402
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
from app.domain.plan import build_plan
from app.schemas.result import PlanPreview  # noqa: E402


def fixture_messages():
    messages: dict[str, dict] = {}
    result_codes: set[str] = set()

    def collect(**values):
        plan = build_plan(Answers.model_validate({"experience": "beginner", **values}))
        plan = PlanPreview.model_validate(plan.model_dump())
        for item in [
            *plan.preferences,
            *plan.boundaries,
            *[item for card in plan.cards for item in [card.title, *card.reason, *card.action]],
        ]:
            messages[item.model_dump_json(by_alias=True)] = item.model_dump(
                mode="json", by_alias=True
            )

    for experience, activity, daily, goal in product(
        Experience, Activity, DailyActivity, SecondaryGoal
    ):
        collect(
            experience=experience, activity=activity, daily_activity=daily, secondary_goals=[goal]
        )
    for limits in (
        [Limitation.none],
        [Limitation.back],
        [Limitation.knees],
        [Limitation.back, Limitation.knees],
    ):
        collect(limitations=limits)
    for sleep, energy in product(Sleep, Energy):
        collect(sleep=sleep, energy=energy)
    habits = [FoodHabit.late_snacks, FoodHabit.sweet_drinks, FoodHabit.sweets]
    for rhythm in MealRhythm:
        collect(meal_rhythm=rhythm, food_habits=[FoodHabit.none])
        for count in range(1, len(habits) + 1):
            for selected in combinations(habits, count):
                collect(meal_rhythm=rhythm, food_habits=list(selected))
    for barrier in Barrier:
        collect(barrier=barrier)
    for window in TimeWindow:
        collect(barrier=Barrier.time, time_window=window)
    for weight, target, goal in [
        (55, 60, "gain"),
        (70, 70, "maintain"),
        (85, 85, "maintain"),
        (110, 110, "maintain"),
    ]:
        calculation = assess(
            CompleteAnswers(
                sex="male",
                age=35,
                height_cm=180,
                weight_kg=weight,
                target_weight_kg=target,
                goal=goal,
                activity="moderate",
            ),
            today=date(2026, 9, 21),
        )
        result_codes.add(calculation.bmi_category)
        result_codes.update(calculation.assumptions)
    return {"messages": list(messages.values()), "resultCodes": sorted(result_codes)}


if __name__ == "__main__":
    print(json.dumps(fixture_messages(), ensure_ascii=True))

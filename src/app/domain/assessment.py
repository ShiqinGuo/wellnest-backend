from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    Activity,
    AssessmentStatus,
    Barrier,
    DailyActivity,
    Energy,
    Experience,
    FlowVersion,
    FoodHabit,
    Goal,
    Limitation,
    MealRhythm,
    RuleVersion,
    SecondaryGoal,
    Sex,
    Sleep,
    Step,
    TimeWindow,
)
from app.domain.guidance import Guidance
from app.domain.plan import PlanPreview
from app.domain.result_codes import BmiCategory, CalculationAssumption
from app.domain.rules import CM_PER_METRE, INPUT_RULES

Age = Annotated[int, Field(strict=True, ge=INPUT_RULES.age_min, le=INPUT_RULES.age_max)]
Height = Annotated[
    float,
    Field(
        strict=True, ge=INPUT_RULES.height_min_cm, le=INPUT_RULES.height_max_cm, allow_inf_nan=False
    ),
]
Weight = Annotated[
    float,
    Field(
        strict=True, ge=INPUT_RULES.weight_min_kg, le=INPUT_RULES.weight_max_kg, allow_inf_nan=False
    ),
]
Version = Annotated[int, Field(strict=True, ge=0)]


class Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sex: Sex | None = None
    goal: Goal | None = None
    age: Age | None = None
    height_cm: Height | None = None
    weight_kg: Weight | None = None
    target_weight_kg: Weight | None = None
    activity: Activity | None = None

    secondary_goals: list[SecondaryGoal] | None = None
    experience: Experience | None = None
    daily_activity: DailyActivity | None = None
    limitations: list[Limitation] | None = None
    sleep: Sleep | None = None
    energy: Energy | None = None
    meal_rhythm: MealRhythm | None = None
    food_habits: list[FoodHabit] | None = None
    barrier: Barrier | None = None
    time_window: TimeWindow | None = None

    @model_validator(mode="after")
    def valid_selections(self):
        for name in ("secondary_goals", "limitations", "food_habits"):
            values = getattr(self, name)
            if values is not None:
                if not values or len(values) != len(set(values)):
                    raise ValueError("多选至少选一项，且不能重复")
                if "none" in values and len(values) != 1:
                    raise ValueError("以上皆无不能与其他选项同时选择")
        if (
            self.time_window is not None
            and self.barrier is not None
            and self.barrier != Barrier.time
        ):
            raise ValueError("只有时间不足时需要选择可用时段")
        return self

    @model_validator(mode="after")
    def coherent_target(self):
        if self.goal and self.weight_kg is not None and self.target_weight_kg is not None:
            delta = self.target_weight_kg - self.weight_kg
            if self.goal == Goal.lose and delta >= 0:
                raise ValueError("减重目标体重需要低于当前体重")
            if self.goal == Goal.gain and delta <= 0:
                raise ValueError("增重目标体重需要高于当前体重")
            if self.goal == Goal.maintain and delta != 0:
                raise ValueError("维持目标的目标体重需要与当前体重一致")
            if abs(delta) > self.weight_kg * INPUT_RULES.max_target_change_ratio:
                raise ValueError("本次评估支持当前体重25%以内的阶段目标")
        if self.height_cm is not None and self.target_weight_kg is not None:
            bmi = self.target_weight_kg / (self.height_cm / CM_PER_METRE) ** 2
            if not INPUT_RULES.target_bmi_min <= bmi <= INPUT_RULES.target_bmi_max:
                raise ValueError("目标体重超出本工具支持的BMI范围18.5–40")
        return self

    def missing(self, flow_version: str = FlowVersion.legacy) -> list[str]:
        from app.domain.flow import FIELD_FOR_STEP, applicable_steps

        return [
            FIELD_FOR_STEP[step]
            for step in applicable_steps(self, flow_version)
            if step in FIELD_FOR_STEP and getattr(self, FIELD_FOR_STEP[step]) is None
        ]


class CompleteAnswers(Answers):
    sex: Sex
    goal: Goal
    age: Age
    height_cm: Height
    weight_kg: Weight
    target_weight_kg: Weight
    activity: Activity


class ProjectionPoint(BaseModel):
    date: date
    weight_kg: float


class Calculation(BaseModel):
    plan_preview: PlanPreview | None = None
    guidance: Guidance | None = None
    algorithm_version: RuleVersion = RuleVersion.wellness_v1
    calculated_on: date
    bmi: float
    bmi_category: BmiCategory
    resting_kcal: int
    maintenance_kcal: int
    suggested_kcal: int
    predicted_goal_date: date
    weekly_change_kg: float
    projection: list[ProjectionPoint]
    assumptions: list[CalculationAssumption]


class AssessmentData(BaseModel):
    id: UUID
    status: AssessmentStatus
    version: int
    flow_version: str
    resume_step_id: Step
    answers: Answers
    updated_at: datetime


class CreateAssessmentCommand(BaseModel):
    source_assessment_id: str | None = None
    start_new: bool = Field(default=False, strict=True)


class UpdateAssessmentCommand(BaseModel):
    expected_version: Version
    answers: Answers = Field(default_factory=Answers)
    resume_step_id: Step | None = None


class SubmitAssessmentCommand(BaseModel):
    expected_version: Version


class SubmissionData(BaseModel):
    result_id: UUID
    status: AssessmentStatus = AssessmentStatus.completed
    version: int


class ResultData(BaseModel):
    assessment_id: UUID
    calculation: Calculation
    is_member: bool

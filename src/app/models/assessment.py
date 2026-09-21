from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

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
    SecondaryGoal,
    Sex,
    Sleep,
    Step,
    TimeWindow,
)
from app.domain.rules import INPUT_RULES
from app.models.base import (
    Base,
    CreatedAtMixin,
    JsonObject,
    Str24,
    TimestampMixin,
    UserFk,
    UuidPk,
)


class Assessment(TimestampMixin, Base):
    __tablename__ = "assessments"

    id: Mapped[UuidPk]
    user_id: Mapped[UserFk] = mapped_column()
    status: Mapped[AssessmentStatus] = mapped_column(server_default=AssessmentStatus.draft.value)
    version: Mapped[int] = mapped_column(server_default="0")
    flow_version: Mapped[Str24] = mapped_column(server_default=FlowVersion.legacy.value)
    resume_step_id: Mapped[Step] = mapped_column(server_default=Step.welcome.value)
    sex: Mapped[Sex | None] = mapped_column()
    goal: Mapped[Goal | None] = mapped_column()
    age: Mapped[int | None] = mapped_column()
    height_cm: Mapped[float | None] = mapped_column()
    weight_kg: Mapped[float | None] = mapped_column()
    target_weight_kg: Mapped[float | None] = mapped_column()
    activity: Mapped[Activity | None] = mapped_column()

    secondary_goals: Mapped[list[SecondaryGoal] | None] = mapped_column(ARRAY(String(32)))
    experience: Mapped[Experience | None] = mapped_column()
    daily_activity: Mapped[DailyActivity | None] = mapped_column()
    limitations: Mapped[list[Limitation] | None] = mapped_column(ARRAY(String(32)))
    sleep: Mapped[Sleep | None] = mapped_column()
    energy: Mapped[Energy | None] = mapped_column()
    meal_rhythm: Mapped[MealRhythm | None] = mapped_column()
    food_habits: Mapped[list[FoodHabit] | None] = mapped_column(ARRAY(String(32)))
    barrier: Mapped[Barrier | None] = mapped_column()
    time_window: Mapped[TimeWindow | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "secondary_goals <@ ARRAY['energy','mobility','routine','strength']::varchar[] AND "
            "cardinality(secondary_goals) BETWEEN 1 AND "
            "4",
            name="assessment_secondary_goals",
        ),
        CheckConstraint(
            "experience IN ('beginner','returning','regular')", name="assessment_experience"
        ),
        CheckConstraint(
            "daily_activity IN ('seated','mixed','on_feet')", name="assessment_daily_activity"
        ),
        CheckConstraint(
            "limitations <@ ARRAY['back','knees','none']::varchar[] AND "
            "cardinality(limitations) BETWEEN 1 AND "
            "3 AND "
            "(NOT ('none' = ANY(limitations)) OR cardinality(limitations) = 1)",
            name="assessment_limitations",
        ),
        CheckConstraint("sleep IN ('short','variable','rested')", name="assessment_sleep"),
        CheckConstraint(
            "energy IN ('low_energy','afternoon_dip','steady')", name="assessment_energy"
        ),
        CheckConstraint(
            "meal_rhythm IN ('regular_meals','skipped_meals','irregular_meals')",
            name="assessment_meal_rhythm",
        ),
        CheckConstraint(
            "food_habits <@ ARRAY['late_snacks','sweet_drinks','sweets','none']::varchar[] AND "
            "cardinality(food_habits) BETWEEN 1 AND "
            "4 AND "
            "(NOT ('none' = ANY(food_habits)) OR cardinality(food_habits) = 1)",
            name="assessment_food_habits",
        ),
        CheckConstraint(
            "barrier IN ('time','motivation','unsure','no_barrier')", name="assessment_barrier"
        ),
        CheckConstraint(
            "time_window IN ('morning','midday','evening','varies')", name="assessment_time_window"
        ),
        CheckConstraint(
            "time_window IS NULL OR (barrier IS NOT NULL AND barrier = 'time')",
            name="assessment_time_window_applicable",
        ),
        CheckConstraint(status.in_(list(AssessmentStatus)), name="assessment_status"),
        CheckConstraint(version >= 0, name="assessment_version"),
        CheckConstraint(
            age.between(INPUT_RULES.age_min, INPUT_RULES.age_max), name="assessment_age"
        ),
        CheckConstraint(
            height_cm.between(INPUT_RULES.height_min_cm, INPUT_RULES.height_max_cm),
            name="assessment_height",
        ),
        CheckConstraint(
            weight_kg.between(INPUT_RULES.weight_min_kg, INPUT_RULES.weight_max_kg),
            name="assessment_weight",
        ),
        CheckConstraint(
            target_weight_kg.between(INPUT_RULES.weight_min_kg, INPUT_RULES.weight_max_kg),
            name="assessment_target",
        ),
        CheckConstraint(sex.in_(list(Sex)), name="assessment_sex"),
        CheckConstraint(goal.in_(list(Goal)), name="assessment_goal"),
        CheckConstraint(activity.in_(list(Activity)), name="assessment_activity"),
        Index("ix_assessment_user_created", "user_id", "created_at"),
    )


class AssessmentResult(CreatedAtMixin, Base):
    __tablename__ = "assessment_results"

    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    input_snapshot: Mapped[JsonObject]
    calculation: Mapped[JsonObject]

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, and_, any_, cast, func, or_
from sqlalchemy.dialects.postgresql import ARRAY, array
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
            and_(
                secondary_goals.column.contained_by(
                    cast(array([item.value for item in SecondaryGoal]), ARRAY(String()))
                ),
                func.cardinality(secondary_goals).between(1, len(SecondaryGoal)),
            ),
            name="assessment_secondary_goals",
        ),
        CheckConstraint(
            experience.in_([item.value for item in Experience]), name="assessment_experience"
        ),
        CheckConstraint(
            daily_activity.in_([item.value for item in DailyActivity]),
            name="assessment_daily_activity",
        ),
        CheckConstraint(
            and_(
                limitations.column.contained_by(
                    cast(array([item.value for item in Limitation]), ARRAY(String()))
                ),
                func.cardinality(limitations).between(1, len(Limitation)),
                or_(
                    ~(any_(limitations) == Limitation.none.value),
                    func.cardinality(limitations) == 1,
                ),
            ),
            name="assessment_limitations",
        ),
        CheckConstraint(sleep.in_([item.value for item in Sleep]), name="assessment_sleep"),
        CheckConstraint(energy.in_([item.value for item in Energy]), name="assessment_energy"),
        CheckConstraint(
            meal_rhythm.in_([item.value for item in MealRhythm]),
            name="assessment_meal_rhythm",
        ),
        CheckConstraint(
            and_(
                food_habits.column.contained_by(
                    cast(array([item.value for item in FoodHabit]), ARRAY(String()))
                ),
                func.cardinality(food_habits).between(1, len(FoodHabit)),
                or_(
                    ~(any_(food_habits) == FoodHabit.none.value), func.cardinality(food_habits) == 1
                ),
            ),
            name="assessment_food_habits",
        ),
        CheckConstraint(barrier.in_([item.value for item in Barrier]), name="assessment_barrier"),
        CheckConstraint(
            time_window.in_([item.value for item in TimeWindow]), name="assessment_time_window"
        ),
        CheckConstraint(
            or_(time_window.is_(None), and_(barrier.is_not(None), barrier == Barrier.time.value)),
            name="assessment_time_window_applicable",
        ),
        CheckConstraint(
            status.in_([item.value for item in AssessmentStatus]), name="assessment_status"
        ),
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
        CheckConstraint(sex.in_([item.value for item in Sex]), name="assessment_sex"),
        CheckConstraint(goal.in_([item.value for item in Goal]), name="assessment_goal"),
        CheckConstraint(
            activity.in_([item.value for item in Activity]), name="assessment_activity"
        ),
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

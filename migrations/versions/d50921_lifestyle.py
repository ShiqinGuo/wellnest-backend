"""Add nullable lifestyle answers; existing drafts keep their original flow."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d50921_lifestyle"
down_revision = "ab4729c48d01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assessments", sa.Column("secondary_goals", postgresql.ARRAY(sa.String(32)), nullable=True)
    )
    op.add_column("assessments", sa.Column("experience", sa.String(32), nullable=True))
    op.add_column("assessments", sa.Column("daily_activity", sa.String(32), nullable=True))
    op.add_column(
        "assessments", sa.Column("limitations", postgresql.ARRAY(sa.String(32)), nullable=True)
    )
    op.add_column("assessments", sa.Column("sleep", sa.String(32), nullable=True))
    op.add_column("assessments", sa.Column("energy", sa.String(32), nullable=True))
    op.add_column("assessments", sa.Column("meal_rhythm", sa.String(32), nullable=True))
    op.add_column(
        "assessments", sa.Column("food_habits", postgresql.ARRAY(sa.String(32)), nullable=True)
    )
    op.add_column("assessments", sa.Column("barrier", sa.String(32), nullable=True))
    op.add_column("assessments", sa.Column("time_window", sa.String(32), nullable=True))

    op.create_check_constraint(
        "assessment_secondary_goals",
        "assessments",
        "secondary_goals <@ ARRAY['energy','mobility','routine','strength']::varchar[] AND "
        "cardinality(secondary_goals) BETWEEN 1 AND "
        "4",
    )
    op.create_check_constraint(
        "assessment_experience", "assessments", "experience IN ('beginner','returning','regular')"
    )
    op.create_check_constraint(
        "assessment_daily_activity", "assessments", "daily_activity IN ('seated','mixed','on_feet')"
    )
    op.create_check_constraint(
        "assessment_limitations",
        "assessments",
        "limitations <@ ARRAY['back','knees','none']::varchar[] AND "
        "cardinality(limitations) BETWEEN 1 AND "
        "3 AND "
        "(NOT ('none' = ANY(limitations)) OR cardinality(limitations) = 1)",
    )
    op.create_check_constraint(
        "assessment_sleep", "assessments", "sleep IN ('short','variable','rested')"
    )
    op.create_check_constraint(
        "assessment_energy", "assessments", "energy IN ('low_energy','afternoon_dip','steady')"
    )
    op.create_check_constraint(
        "assessment_meal_rhythm",
        "assessments",
        "meal_rhythm IN ('regular_meals','skipped_meals','irregular_meals')",
    )
    op.create_check_constraint(
        "assessment_food_habits",
        "assessments",
        "food_habits <@ ARRAY['late_snacks','sweet_drinks','sweets','none']::varchar[] AND "
        "cardinality(food_habits) BETWEEN 1 AND "
        "4 AND "
        "(NOT ('none' = ANY(food_habits)) OR cardinality(food_habits) = 1)",
    )
    op.create_check_constraint(
        "assessment_barrier",
        "assessments",
        "barrier IN ('time','motivation','unsure','no_barrier')",
    )
    op.create_check_constraint(
        "assessment_time_window",
        "assessments",
        "time_window IN ('morning','midday','evening','varies')",
    )
    op.create_check_constraint(
        "assessment_time_window_applicable",
        "assessments",
        "time_window IS NULL OR (barrier IS NOT NULL AND barrier = 'time')",
    )


def downgrade():
    op.drop_constraint("assessment_time_window_applicable", "assessments", type_="check")
    op.drop_constraint("assessment_time_window", "assessments", type_="check")
    op.drop_constraint("assessment_barrier", "assessments", type_="check")
    op.drop_constraint("assessment_food_habits", "assessments", type_="check")
    op.drop_constraint("assessment_meal_rhythm", "assessments", type_="check")
    op.drop_constraint("assessment_energy", "assessments", type_="check")
    op.drop_constraint("assessment_sleep", "assessments", type_="check")
    op.drop_constraint("assessment_limitations", "assessments", type_="check")
    op.drop_constraint("assessment_daily_activity", "assessments", type_="check")
    op.drop_constraint("assessment_experience", "assessments", type_="check")
    op.drop_constraint("assessment_secondary_goals", "assessments", type_="check")

    op.drop_column("assessments", "time_window")
    op.drop_column("assessments", "barrier")
    op.drop_column("assessments", "food_habits")
    op.drop_column("assessments", "meal_rhythm")
    op.drop_column("assessments", "energy")
    op.drop_column("assessments", "sleep")
    op.drop_column("assessments", "limitations")
    op.drop_column("assessments", "daily_activity")
    op.drop_column("assessments", "experience")
    op.drop_column("assessments", "secondary_goals")

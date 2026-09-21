"""Append-only guidance retries, separate from immutable numerical results."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ab4729c48d01"
down_revision = "cb64316df428"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guidance_attempts",
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("guidance", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessment_results.assessment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assessment_id", "revision"),
        sa.CheckConstraint("revision > 0", name="guidance_revision"),
    )


def downgrade():
    op.drop_table("guidance_attempts")

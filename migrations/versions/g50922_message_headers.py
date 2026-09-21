"""Replace the dedicated trace column with generic message headers."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "g50922_message_headers"
down_revision = "f50922_trace_context"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outbox_events",
        sa.Column(
            "headers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.execute("""UPDATE outbox_events SET headers=jsonb_build_object('traceparent',traceparent)
                  WHERE traceparent IS NOT NULL""")
    op.drop_column("outbox_events", "traceparent")


def downgrade():
    op.add_column("outbox_events", sa.Column("traceparent", sa.String(55), nullable=True))
    op.execute("UPDATE outbox_events SET traceparent=headers->>'traceparent'")
    op.drop_column("outbox_events", "headers")

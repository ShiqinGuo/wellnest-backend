"""Persist the originating trace context across Outbox relay and recovery."""

import sqlalchemy as sa
from alembic import op

revision = "f50922_trace_context"
down_revision = "e50921_payments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("outbox_events", sa.Column("traceparent", sa.String(55), nullable=True))


def downgrade():
    op.drop_column("outbox_events", "traceparent")

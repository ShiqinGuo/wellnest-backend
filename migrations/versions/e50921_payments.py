"""Durable asynchronous payments; retain legacy entitlements.

Downgrade discards new payment history. Restore backup instead in production.
"""

from alembic import op

revision = "e50921_payments"
down_revision = "d50921_lifestyle"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE payments (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	plan_id VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	amount_minor INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	provider VARCHAR(16) NOT NULL, 
	provider_transaction_id UUID, 
	checkout_url TEXT, 
	next_check_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_refresh_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT payment_amount_positive CHECK (amount_minor > 0), 
	CONSTRAINT payment_status CHECK (status IN ('pending', 'succeeded', 'failed', 'closed')), 
	CONSTRAINT payment_currency CHECK (currency IN ('CNY')), 
	CONSTRAINT payment_provider CHECK (provider IN ('mock')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (provider_transaction_id)
)

""")
    op.execute("""CREATE INDEX payment_due ON payments (next_check_at) WHERE status='pending'""")
    op.execute(
        """CREATE UNIQUE INDEX payment_one_pending ON payments (user_id, plan_id)
WHERE status='pending'"""
    )
    op.execute("""
CREATE TABLE payment_webhook_inbox (
	id UUID NOT NULL, 
	payment_id UUID NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	payload JSONB NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	rejection_code VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT webhook_status CHECK (status IN ('pending', 'processed', 'rejected')), 
	FOREIGN KEY(payment_id) REFERENCES payments (id)
)

""")
    op.execute("""
CREATE TABLE outbox_events (
	id UUID NOT NULL, 
	task VARCHAR(40) NOT NULL, 
	aggregate_id UUID NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	attempts INTEGER DEFAULT '0' NOT NULL, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	lease_token UUID, 
	lease_until TIMESTAMP WITH TIME ZONE, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	last_error VARCHAR(128), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT outbox_status CHECK (status IN ('pending', 'published', 'failed')), 
	CONSTRAINT outbox_task CHECK (task IN ('payment.create', 'payment.reconcile',
'payment.process_webhook', 'mock.deliver_webhook')), 
	CONSTRAINT outbox_attempts CHECK (attempts >= 0)
)

""")
    op.execute(
        """CREATE INDEX outbox_due ON outbox_events (available_at) WHERE processed_at IS NULL"""
    )
    op.execute(
        """CREATE UNIQUE INDEX outbox_one_open_task ON outbox_events (task, aggregate_id)
WHERE processed_at IS NULL AND status <> 'failed'"""
    )
    op.execute("""
CREATE TABLE mock_provider_payments (
	id UUID NOT NULL, 
	merchant_payment_id UUID NOT NULL, 
	amount_minor INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	checkout_token VARCHAR(64) NOT NULL, 
	event_id UUID NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT mock_provider_amount CHECK (amount_minor > 0), 
	CONSTRAINT mock_provider_currency CHECK (currency IN ('CNY')), 
	CONSTRAINT mock_provider_status CHECK (status IN ('pending', 'succeeded', 'failed', 'closed')), 
	UNIQUE (merchant_payment_id), 
	UNIQUE (checkout_token), 
	UNIQUE (event_id)
)

""")
    op.execute(
        "ALTER TABLE subscriptions ADD COLUMN source_payment_id uuid UNIQUE REFERENCES payments(id)"
    )


def downgrade():
    op.drop_column("subscriptions", "source_payment_id")
    op.drop_table("mock_provider_payments")
    op.drop_table("outbox_events")
    op.drop_table("payment_webhook_inbox")
    op.drop_table("payments")

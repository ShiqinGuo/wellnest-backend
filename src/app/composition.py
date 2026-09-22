"""Payment object graph shared by HTTP, Queue/Cron adapters and integration tests."""

from app.database import Database
from app.payment_settings import PaymentSettings
from app.providers.mock_payment import PaymentGateway
from app.repositories.assessment import AssessmentRepository
from app.repositories.command import CommandRepository
from app.repositories.mock_provider import MockProviderRepository
from app.repositories.outbox import OutboxRepository
from app.repositories.payment import PaymentRepository
from app.repositories.payment_webhook import PaymentWebhookRepository
from app.services.command import CommandService
from app.services.mock_provider import MockProviderService
from app.services.payment import PaymentService
from app.services.payment_workflow import PaymentWorkflow


def build_payment_workflow(
    db: Database,
    settings: PaymentSettings,
    gateway: PaymentGateway,
) -> PaymentWorkflow:
    outbox = OutboxRepository(db)
    repository = PaymentRepository(db)
    locks = CommandRepository(db)
    service = PaymentService(
        repository, AssessmentRepository(db), CommandService(locks), settings, outbox, locks
    )
    provider = MockProviderService(MockProviderRepository(db), settings, outbox)
    return PaymentWorkflow(
        db, settings, gateway, outbox, repository, PaymentWebhookRepository(db), service, provider
    )

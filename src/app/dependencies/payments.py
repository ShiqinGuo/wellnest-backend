import hmac
from typing import Annotated

from fastapi import Depends, Header

from app.dependencies.database import DatabaseDep
from app.errors import AppError, ErrorCode
from app.payment_settings import PaymentSettings, payment_settings
from app.providers.mock_payment import MockPaymentGateway
from app.repositories.mock_provider import MockProviderRepository
from app.services.mock_provider import MockProviderService
from app.services.payment_workflow import PaymentWorkflow

PaymentSettingsDep = Annotated[PaymentSettings, Depends(payment_settings)]


async def provider_auth(settings: PaymentSettingsDep, authorization: str = Header(default="")):
    if not hmac.compare_digest(
        authorization.encode(), f"Bearer {settings.provider_key.get_secret_value()}".encode()
    ):
        raise AppError(ErrorCode.invalid_provider_key, "Invalid provider credentials", 401)


async def mock_provider(db: DatabaseDep, settings: PaymentSettingsDep) -> MockProviderService:
    return MockProviderService(MockProviderRepository(db), settings)


async def workflow(db: DatabaseDep, settings: PaymentSettingsDep) -> PaymentWorkflow:
    return PaymentWorkflow(db, settings, MockPaymentGateway(settings))


MockProviderDep = Annotated[MockProviderService, Depends(mock_provider)]
PaymentWorkflowDep = Annotated[PaymentWorkflow, Depends(workflow)]

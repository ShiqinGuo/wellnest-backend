from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.dependencies.auth import CommandKeyDep, IdentityDep
from app.dependencies.payments import (
    MockProviderDep,
    PaymentSettingsDep,
    PaymentWorkflowDep,
    provider_auth,
)
from app.dependencies.services import PaymentServiceDep
from app.domain.payment import ChannelCreate, ChannelNotification, ChannelPayment, CheckoutConfirm
from app.errors import AppError, ErrorCode
from app.providers.mock_payment import verify
from app.schemas.payment import Accepted, PayInput, PaymentView

router = APIRouter(prefix="/api", tags=["payments"])
# The shared enums are registered by the ChannelPayment provider endpoints.
notification_schema = ChannelNotification.model_json_schema(
    ref_template="#/components/schemas/{model}"
)
notification_schema.pop("$defs", None)


@router.post("/payments", status_code=HTTPStatus.CREATED)
async def create_payment(
    payload: PayInput,
    key: CommandKeyDep,
    me: IdentityDep,
    service: PaymentServiceDep,
) -> PaymentView:
    return PaymentView.from_data(await service.create(me.user_id, key, payload.to_command()))


@router.get("/payments/{payment_id}")
async def get_payment(payment_id: UUID, me: IdentityDep, service: PaymentServiceDep) -> PaymentView:
    return PaymentView.from_data(await service.get(me.user_id, payment_id))


@router.post("/payments/{payment_id}/refresh", status_code=HTTPStatus.ACCEPTED)
async def refresh(payment_id: UUID, me: IdentityDep, service: PaymentServiceDep) -> Accepted:
    await service.refresh(me.user_id, payment_id)
    return Accepted()


@router.post(
    "/webhooks/payments/mock",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": notification_schema}},
        }
    },
)
async def webhook(
    request: Request,
    settings: PaymentSettingsDep,
    service: PaymentWorkflowDep,
    x_payment_timestamp: str = Header(default=""),
    x_payment_signature: str = Header(default=""),
) -> Accepted:
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > settings.max_webhook_bytes:
            raise AppError(ErrorCode.webhook_too_large)
    body = bytes(chunks)
    verify(body, x_payment_timestamp, x_payment_signature, settings)
    from pydantic import ValidationError

    try:
        notification = ChannelNotification.model_validate_json(body)
    except ValidationError as exc:
        raise AppError(ErrorCode.invalid_notification) from exc
    await service.accept_webhook(notification)
    return Accepted()


@router.post(
    "/mock-provider/payments", dependencies=[Depends(provider_auth)], status_code=HTTPStatus.CREATED
)
async def provider_create(payload: ChannelCreate, service: MockProviderDep) -> ChannelPayment:
    return await service.create(payload)


@router.get("/mock-provider/payments/{merchant_payment_id}", dependencies=[Depends(provider_auth)])
async def provider_query(merchant_payment_id: UUID, service: MockProviderDep) -> ChannelPayment:
    return await service.query(merchant_payment_id)


@router.get("/mock-checkout/{token}")
async def checkout(token: str, service: MockProviderDep) -> ChannelPayment:
    return await service.checkout(token)


@router.post("/mock-checkout/{token}/confirm")
async def confirm(token: str, payload: CheckoutConfirm, service: MockProviderDep) -> ChannelPayment:
    return await service.checkout(token, payload)

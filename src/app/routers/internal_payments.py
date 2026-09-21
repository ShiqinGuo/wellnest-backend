"""Authenticated fetch boundary for region-placed payment execution."""

import hmac

from fastapi import APIRouter, Depends, Header, Request

from app.dependencies.payments import PaymentSettingsDep
from app.domain.queue_message import DeliveryResult, PaymentMessage
from app.errors import AppError, ErrorCode
from app.worker_runtime import delivery, relay


async def internal_auth(settings: PaymentSettingsDep, authorization: str = Header(default="")):
    key = settings.internal_key
    if key is None or not hmac.compare_digest(
        authorization.encode(), f"Bearer {key.get_secret_value()}".encode()
    ):
        raise AppError(ErrorCode.invalid_internal_key)


router = APIRouter(
    prefix="/_internal/payments", include_in_schema=False, dependencies=[Depends(internal_auth)]
)


@router.post("/consume")
async def consume(payload: PaymentMessage, request: Request) -> DeliveryResult:
    service = delivery(request.scope["env"])
    try:
        return DeliveryResult(retry_after=await service.consume(payload))
    finally:
        await service.db.release()


@router.post("/recover")
async def recover(request: Request) -> DeliveryResult:
    await relay(request.scope["env"], reconcile=True)
    return DeliveryResult()

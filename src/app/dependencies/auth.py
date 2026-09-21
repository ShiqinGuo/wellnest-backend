from typing import Annotated

from fastapi import Depends, Header, Request

from app.dependencies.services import SessionServiceDep
from app.domain.session import IdentityData
from app.errors import AppError, ErrorCode
from app.settings import RUNTIME

SESSION_COOKIE = RUNTIME.session_cookie


async def get_identity(request: Request, service: SessionServiceDep) -> IdentityData:
    token = request.cookies.get(SESSION_COOKIE)
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    return await service.authenticate(token)


async def get_command_key(
    idempotency_key: Annotated[
        str,
        Header(
            min_length=RUNTIME.idempotency_key_min_length,
            max_length=RUNTIME.idempotency_key_max_length,
        ),
    ],
) -> str:
    if not all(c.isalnum() or c in "-_.:" for c in idempotency_key):
        raise AppError(ErrorCode.invalid_command_key, "操作标识格式无效", 422)
    return idempotency_key


IdentityDep = Annotated[IdentityData, Depends(get_identity)]
CommandKeyDep = Annotated[str, Depends(get_command_key)]

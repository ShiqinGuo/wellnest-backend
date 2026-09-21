import hashlib
import json
from collections.abc import Awaitable, Callable
from uuid import UUID

from pydantic import BaseModel

from app.errors import AppError, ErrorCode
from app.repositories.command import CommandRepository


class CommandService:
    """One transaction and per-user lock own both the state change and its receipt."""

    def __init__(self, repository: CommandRepository):
        self.repository = repository

    async def release_connection(self) -> None:
        """End the read phase before external I/O; transactions cannot be suspended."""
        await self.repository.release_connection()

    async def replay[T: BaseModel](
        self, user_id: UUID, command: str, key: str, payload: BaseModel, result_type: type[T]
    ) -> T | None:
        fingerprint = hashlib.sha256(
            json.dumps(payload.model_dump(mode="json", exclude_unset=True), sort_keys=True).encode()
        ).hexdigest()
        receipt = await self.repository.receipt(user_id, command, key)
        if receipt is None:
            return None
        if receipt.fingerprint != fingerprint:
            raise AppError(ErrorCode.idempotency_conflict, "此操作标识已用于其他内容，请刷新后重试")
        return self.repository.decode(receipt, result_type)

    async def run[T: BaseModel](
        self,
        user_id: UUID,
        command: str,
        key: str,
        payload: BaseModel,
        operation: Callable[[], Awaitable[T]],
        result_type: type[T],
    ) -> T:
        fingerprint = hashlib.sha256(
            json.dumps(payload.model_dump(mode="json", exclude_unset=True), sort_keys=True).encode()
        ).hexdigest()
        async with self.repository.transaction():
            await self.repository.lock_user(user_id)
            receipt = await self.repository.receipt(user_id, command, key)
            if receipt:
                if receipt.fingerprint != fingerprint:
                    raise AppError(
                        ErrorCode.idempotency_conflict, "此操作标识已用于其他内容，请刷新后重试"
                    )
                return self.repository.decode(receipt, result_type)
            result = await operation()
            await self.repository.record(user_id, command, key, fingerprint, result)
            return result

import json
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from pydantic.alias_generators import to_snake
from sqlalchemy import insert, select

from app.database import Database
from app.models import CommandReceipt, User


@dataclass(frozen=True)
class StoredReceipt:
    fingerprint: str
    response_json: str


class CommandRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    def transaction(self):
        return self.conn.transaction()

    async def release_connection(self) -> None:
        await self.conn.release()

    async def lock_user(self, user_id: UUID) -> None:
        await self.conn.fetchrow(select(User.id).where(User.id == user_id).with_for_update())

    async def receipt(self, user_id: UUID, command: str, key: str) -> StoredReceipt | None:
        row = await self.conn.fetchrow(
            select(CommandReceipt.fingerprint, CommandReceipt.response).where(
                CommandReceipt.user_id == user_id,
                CommandReceipt.command == command,
                CommandReceipt.key == key,
            )
        )
        return StoredReceipt(row["fingerprint"], row["response"]) if row else None

    @staticmethod
    def decode[T: BaseModel](receipt: StoredReceipt, result_type: type[T]) -> T:
        # Pre-refactor receipts contain camelCase API snapshots. Preserve their replay semantics.
        payload = {to_snake(k): v for k, v in json.loads(receipt.response_json).items()}
        if "answers" in payload:
            payload["answers"] = {to_snake(k): v for k, v in payload["answers"].items()}
        return result_type.model_validate(payload)

    async def record(
        self, user_id: UUID, command: str, key: str, fingerprint: str, result: BaseModel
    ) -> None:
        await self.conn.execute(
            insert(CommandReceipt).values(
                user_id=user_id,
                command=command,
                key=key,
                fingerprint=fingerprint,
                response=result.model_dump(mode="json"),
            )
        )

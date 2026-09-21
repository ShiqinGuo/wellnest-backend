from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, JsonObject, Str64, Str128, UserFk


class CommandReceipt(CreatedAtMixin, Base):
    __tablename__ = "command_receipts"

    user_id: Mapped[UserFk] = mapped_column(primary_key=True)
    command: Mapped[Str128] = mapped_column(primary_key=True)
    key: Mapped[Str128] = mapped_column(primary_key=True)
    fingerprint: Mapped[Str64]
    response: Mapped[JsonObject]

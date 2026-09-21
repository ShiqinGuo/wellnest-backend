from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, Str64, Timestamp, UserFk, UuidPk


class User(CreatedAtMixin, Base):
    __tablename__ = "users"

    id: Mapped[UuidPk]


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UuidPk]
    user_id: Mapped[UserFk]
    token_hash: Mapped[Str64] = mapped_column(unique=True)
    expires_at: Mapped[Timestamp]

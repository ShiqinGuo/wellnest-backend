from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, JsonObject


class GuidanceAttempt(CreatedAtMixin, Base):
    __tablename__ = "guidance_attempts"

    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_results.assessment_id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(primary_key=True)
    guidance: Mapped[JsonObject]

    __table_args__ = (CheckConstraint(revision > 0, name="guidance_revision"),)

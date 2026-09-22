from uuid import UUID

from sqlalchemy import insert, select

from app.database import Database
from app.domain.assessment import CompleteAnswers
from app.domain.guidance import Guidance
from app.models import AssessmentResult, GuidanceAttempt


class GuidanceRepository:
    def __init__(self, db: Database):
        self.db = db

    async def latest(self, assessment_id: UUID) -> Guidance | None:
        row = await self.db.fetchrow(
            select(GuidanceAttempt.guidance)
            .where(GuidanceAttempt.assessment_id == assessment_id)
            .order_by(GuidanceAttempt.revision.desc())
            .limit(1)
        )
        return Guidance.model_validate_json(row["guidance"]) if row else None

    async def snapshot(self, assessment_id: UUID) -> CompleteAnswers:
        row = await self.db.fetchrow(
            select(AssessmentResult.input_snapshot).where(
                AssessmentResult.assessment_id == assessment_id
            )
        )
        if row is None:
            raise LookupError("Assessment result snapshot is missing")
        return CompleteAnswers.model_validate_json(row["input_snapshot"])

    async def append(self, assessment_id: UUID, guidance: Guidance) -> None:
        await self.db.execute(
            insert(GuidanceAttempt).values(
                assessment_id=assessment_id,
                revision=guidance.revision,
                guidance=guidance.model_dump(mode="json"),
            )
        )

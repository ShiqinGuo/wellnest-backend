from uuid import UUID

from app.database import Database
from app.domain.assessment import CompleteAnswers
from app.domain.guidance import Guidance


class GuidanceRepository:
    def __init__(self, db: Database):
        self.db = db

    async def latest(self, assessment_id: UUID) -> Guidance | None:
        row = await self.db.fetchrow(
            "SELECT guidance FROM guidance_attempts WHERE assessment_id=$1 "
            "ORDER BY revision DESC LIMIT 1",
            assessment_id,
        )
        return Guidance.model_validate_json(row["guidance"]) if row else None

    async def snapshot(self, assessment_id: UUID) -> CompleteAnswers:
        row = await self.db.fetchrow(
            "SELECT input_snapshot FROM assessment_results WHERE assessment_id=$1", assessment_id
        )
        return CompleteAnswers.model_validate_json(row["input_snapshot"])

    async def append(self, assessment_id: UUID, guidance: Guidance) -> None:
        await self.db.execute(
            "INSERT INTO guidance_attempts(assessment_id,revision,guidance) "
            "VALUES($1,$2,$3::jsonb)",
            assessment_id,
            guidance.revision,
            guidance.model_dump_json(),
        )

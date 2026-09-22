from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import exists, func, insert, select, update

from app.database import Database
from app.domain.assessment import Answers, AssessmentData, Calculation, CompleteAnswers, ResultData
from app.domain.enums import AssessmentStatus, FlowVersion, Step
from app.domain.result_compatibility import load_calculation
from app.models import Assessment, AssessmentResult, Subscription


def assessment_data(row: asyncpg.Record | None) -> AssessmentData:
    if row is None:
        raise LookupError("Expected assessment row is missing")
    return AssessmentData(
        id=row["id"],
        status=row["status"],
        version=row["version"],
        flow_version=row["flow_version"],
        resume_step_id=row["resume_step_id"],
        updated_at=row["updated_at"],
        answers=Answers.model_validate({field: row[field] for field in Answers.model_fields}),
    )


class AssessmentRepository:
    def __init__(self, conn: Database):
        self.conn = conn

    async def get(
        self, user_id: UUID, assessment_id: UUID, *, lock: bool = False
    ) -> AssessmentData | None:
        query = select(Assessment).where(
            Assessment.user_id == user_id, Assessment.id == assessment_id
        )
        if lock:
            query = query.with_for_update()
        row = await self.conn.fetchrow(query)
        return assessment_data(row) if row else None

    async def current(self, user_id: UUID) -> AssessmentData | None:
        row = await self.conn.fetchrow(
            select(Assessment)
            .where(Assessment.user_id == user_id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(1)
        )
        return assessment_data(row) if row else None

    async def create(self, user_id: UUID, answers: Answers) -> AssessmentData:
        row = await self.conn.fetchrow(
            insert(Assessment)
            .values(
                id=uuid4(),
                user_id=user_id,
                flow_version=FlowVersion.lifestyle,
                **answers.model_dump(),
            )
            .returning(Assessment)
        )
        return assessment_data(row)

    async def update(self, assessment_id: UUID, answers: Answers, step: Step) -> AssessmentData:
        row = await self.conn.fetchrow(
            update(Assessment)
            .where(Assessment.id == assessment_id)
            .values(
                **answers.model_dump(),
                resume_step_id=step,
                version=Assessment.version + 1,
                updated_at=func.now(),
            )
            .returning(Assessment)
        )
        return assessment_data(row)

    async def complete(
        self,
        assessment_id: UUID,
        answers: CompleteAnswers,
        result: Calculation,
        status: AssessmentStatus,
    ) -> None:
        await self.conn.execute(
            insert(AssessmentResult).values(
                assessment_id=assessment_id,
                input_snapshot=answers.model_dump(mode="json"),
                calculation=result.model_dump(mode="json"),
            )
        )
        await self.conn.execute(
            update(Assessment)
            .where(Assessment.id == assessment_id)
            .values(
                status=status,
                resume_step_id=Step.result,
                version=Assessment.version + 1,
                updated_at=func.now(),
            )
        )

    async def result(self, user_id: UUID, assessment_id: UUID) -> ResultData | None:
        row = await self.conn.fetchrow(
            select(
                AssessmentResult.calculation,
                AssessmentResult.input_snapshot,
                Subscription.user_id.label("member"),
            )
            .select_from(Assessment)
            .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.id)
            .outerjoin(Subscription, Subscription.user_id == Assessment.user_id)
            .where(Assessment.user_id == user_id, Assessment.id == assessment_id)
        )
        if row is None:
            return None
        return ResultData(
            assessment_id=assessment_id,
            calculation=load_calculation(row["calculation"], row["input_snapshot"]),
            is_member=row["member"] is not None,
        )

    async def has_completed(self, user_id: UUID) -> bool:
        return await self.conn.fetchval(
            select(
                exists().where(
                    Assessment.user_id == user_id, Assessment.status == AssessmentStatus.completed
                )
            )
        )

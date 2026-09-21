from uuid import UUID, uuid4

import asyncpg

from app.database import Database
from app.domain.assessment import Answers, AssessmentData, Calculation, CompleteAnswers, ResultData
from app.domain.enums import AssessmentStatus, FlowVersion, Step
from app.domain.result_compatibility import load_calculation


def assessment_data(row: asyncpg.Record) -> AssessmentData:
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
        sql = "SELECT * FROM assessments WHERE user_id=$1 AND id=$2"
        row = await self.conn.fetchrow(
            sql + (" FOR UPDATE" if lock else ""), user_id, assessment_id
        )
        return assessment_data(row) if row else None

    async def current(self, user_id: UUID) -> AssessmentData | None:
        row = await self.conn.fetchrow(
            "SELECT * FROM assessments WHERE user_id=$1 ORDER BY created_at DESC, id DESC LIMIT 1",
            user_id,
        )
        return assessment_data(row) if row else None

    async def create(self, user_id: UUID, answers: Answers) -> AssessmentData:
        row = await self.conn.fetchrow(
            """INSERT INTO assessments
            (id,user_id,sex,goal,age,height_cm,weight_kg,target_weight_kg,activity,flow_version,secondary_goals,experience,daily_activity,limitations,sleep,energy,meal_rhythm,food_habits,barrier,time_window)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
            RETURNING *""",
            uuid4(),
            user_id,
            answers.sex,
            answers.goal,
            answers.age,
            answers.height_cm,
            answers.weight_kg,
            answers.target_weight_kg,
            answers.activity,
            FlowVersion.lifestyle,
            answers.secondary_goals,
            answers.experience,
            answers.daily_activity,
            answers.limitations,
            answers.sleep,
            answers.energy,
            answers.meal_rhythm,
            answers.food_habits,
            answers.barrier,
            answers.time_window,
        )
        return assessment_data(row)

    async def update(self, assessment_id: UUID, answers: Answers, step: Step) -> AssessmentData:
        row = await self.conn.fetchrow(
            """UPDATE assessments SET sex=$2,goal=$3,age=$4,height_cm=$5,weight_kg=$6,
            target_weight_kg=$7,activity=$8,resume_step_id=$9,
            secondary_goals=$10,experience=$11,daily_activity=$12,limitations=$13,sleep=$14,energy=$15,meal_rhythm=$16,food_habits=$17,barrier=$18,time_window=$19,
            version=version+1,updated_at=now()
            WHERE id=$1 RETURNING *""",
            assessment_id,
            answers.sex,
            answers.goal,
            answers.age,
            answers.height_cm,
            answers.weight_kg,
            answers.target_weight_kg,
            answers.activity,
            step,
            answers.secondary_goals,
            answers.experience,
            answers.daily_activity,
            answers.limitations,
            answers.sleep,
            answers.energy,
            answers.meal_rhythm,
            answers.food_habits,
            answers.barrier,
            answers.time_window,
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
            "INSERT INTO assessment_results(assessment_id,input_snapshot,calculation) "
            "VALUES($1,$2::jsonb,$3::jsonb)",
            assessment_id,
            answers.model_dump_json(),
            result.model_dump_json(),
        )
        await self.conn.execute(
            "UPDATE assessments SET status=$2,resume_step_id=$3,"
            "version=version+1,updated_at=now() WHERE id=$1",
            assessment_id,
            status,
            Step.result,
        )

    async def result(self, user_id: UUID, assessment_id: UUID) -> ResultData | None:
        row = await self.conn.fetchrow(
            """SELECT r.calculation, r.input_snapshot, s.user_id AS member FROM assessments a
            JOIN assessment_results r ON r.assessment_id=a.id
            LEFT JOIN subscriptions s ON s.user_id=a.user_id
            WHERE a.user_id=$1 AND a.id=$2""",
            user_id,
            assessment_id,
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
            "SELECT EXISTS(SELECT 1 FROM assessments WHERE user_id=$1 AND status=$2)",
            user_id,
            AssessmentStatus.completed,
        )

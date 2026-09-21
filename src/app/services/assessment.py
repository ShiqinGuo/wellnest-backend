from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from pydantic.alias_generators import to_camel

from app.domain.assessment import (
    Answers,
    AssessmentData,
    CompleteAnswers,
    CreateAssessmentCommand,
    ResultData,
    SubmissionData,
    SubmitAssessmentCommand,
    UpdateAssessmentCommand,
)
from app.domain.calculation import assess
from app.domain.enums import AssessmentEvent, AssessmentStatus, Barrier, FlowVersion, Goal
from app.domain.flow import FLOW_STEPS, AssessmentNavigation
from app.domain.plan import build_plan
from app.domain.state_machine import AssessmentStateMachine
from app.errors import AppError, ErrorCode
from app.providers.typesafe import JevClient
from app.repositories.assessment import AssessmentRepository
from app.repositories.guidance import GuidanceRepository
from app.services.command import CommandService


class AssessmentService:
    def __init__(self, repository: AssessmentRepository, commands: CommandService, jev: JevClient):
        self.repository = repository
        self.commands = commands
        self.jev = jev

    async def get(
        self, user_id: UUID, assessment_id: UUID, *, lock: bool = False
    ) -> AssessmentData:
        assessment = await self.repository.get(user_id, assessment_id, lock=lock)
        if assessment is None:
            raise AppError(ErrorCode.not_found, "未找到这份测评", 404)
        return assessment

    @staticmethod
    def check_version(assessment: AssessmentData, expected: int) -> None:
        if assessment.version != expected:
            raise AppError(
                ErrorCode.version_conflict,
                "测评已在其他页面更新，请载入最新数据再继续",
                details={"currentVersion": assessment.version},
            )

    async def create(
        self, user_id: UUID, key: str, command: CreateAssessmentCommand
    ) -> AssessmentData:
        async def operation() -> AssessmentData:
            current = await self.repository.current(user_id)
            if current and current.status == AssessmentStatus.draft and not command.start_new:
                return current
            answers = Answers()
            if command.source_assessment_id:
                try:
                    source_id = UUID(command.source_assessment_id)
                except ValueError as exc:
                    raise AppError(ErrorCode.invalid_source, "来源测评格式无效", 422) from exc
                answers = (await self.get(user_id, source_id, lock=True)).answers
            return await self.repository.create(user_id, answers)

        return await self.commands.run(
            user_id, "assessment.create", key, command, operation, AssessmentData
        )

    async def patch(
        self, user_id: UUID, assessment_id: UUID, key: str, command: UpdateAssessmentCommand
    ) -> AssessmentData:
        async def operation() -> AssessmentData:
            current = await self.get(user_id, assessment_id, lock=True)
            self.check_version(current, command.expected_version)
            AssessmentStateMachine.transition(current.status, AssessmentEvent.edit)
            combined = current.answers.model_dump() | command.answers.model_dump(exclude_unset=True)
            if current.flow_version not in FLOW_STEPS:
                raise AppError(ErrorCode.unsupported_flow, "此问卷版本暂不支持编辑", 409)
            if combined["barrier"] != Barrier.time:
                if command.answers.time_window is not None:
                    raise AppError(ErrorCode.invalid_answers, "当前回答不适用时间追问", 422)
                combined["time_window"] = None
            if current.flow_version != FlowVersion.lifestyle:
                from app.domain.flow import FIELD_FOR_STEP, GUIDED_STEPS, LIFESTYLE_STEPS

                new_fields = {
                    FIELD_FOR_STEP[s]
                    for s in LIFESTYLE_STEPS
                    if s not in GUIDED_STEPS and s in FIELD_FOR_STEP
                }
                if new_fields & command.answers.model_fields_set:
                    raise AppError(
                        ErrorCode.invalid_answers, "旧版问卷不支持新增画像字段，请重新测评", 422
                    )
            if combined["goal"] == Goal.maintain:
                combined["target_weight_kg"] = combined["weight_kg"]
            try:
                answers = Answers.model_validate(combined)
            except ValidationError as exc:
                raise AppError(ErrorCode.invalid_answers, str(exc.errors()[0]["msg"]), 422) from exc
            step = (
                AssessmentNavigation.transition(
                    current.resume_step_id, command.resume_step_id, answers, current.flow_version
                )
                if command.resume_step_id is not None
                else AssessmentNavigation.reconcile(
                    current.resume_step_id, answers, current.flow_version
                )
            )
            if current.answers == answers and step == current.resume_step_id:
                return current
            return await self.repository.update(assessment_id, answers, step)

        return await self.commands.run(
            user_id, f"assessment.patch:{assessment_id}", key, command, operation, AssessmentData
        )

    async def submit(
        self, user_id: UUID, assessment_id: UUID, key: str, command: SubmitAssessmentCommand
    ) -> SubmissionData:
        command_name = f"assessment.submit:{assessment_id}"
        replay = await self.commands.replay(user_id, command_name, key, command, SubmissionData)
        if replay:
            return replay
        initial = await self.get(user_id, assessment_id)
        self.check_version(initial, command.expected_version)
        complete = None
        calculation = None
        if initial.status != AssessmentStatus.completed:
            if initial.flow_version not in FLOW_STEPS:
                raise AppError(ErrorCode.unsupported_flow, "此问卷版本暂不支持提交", 409)
            if initial.answers.missing(initial.flow_version):
                raise AppError(
                    ErrorCode.incomplete_assessment,
                    "还有必填信息未完成",
                    422,
                    {
                        "missingFields": [
                            to_camel(f) for f in initial.answers.missing(initial.flow_version)
                        ]
                    },
                )
            try:
                complete = CompleteAnswers.model_validate(initial.answers.model_dump())
                calculation = assess(complete, today=datetime.now(UTC).date())
                calculation.plan_preview = build_plan(complete)
            except ValueError as exc:
                raise AppError(ErrorCode.unsupported_estimate, str(exc), 422) from exc
            # No transaction or row lock is held across external inference.
            await self.commands.release_connection()
            calculation.guidance = await self.jev.judge(complete)

        async def operation() -> SubmissionData:
            current = await self.get(user_id, assessment_id, lock=True)
            self.check_version(current, command.expected_version)
            if current.status == AssessmentStatus.completed:
                return SubmissionData(result_id=assessment_id, version=current.version)
            if complete is None or calculation is None:
                raise RuntimeError("Missing prepared assessment")
            status = AssessmentStateMachine.transition(current.status, AssessmentEvent.submit)
            await self.repository.complete(assessment_id, complete, calculation, status)
            return SubmissionData(result_id=assessment_id, version=current.version + 1)

        return await self.commands.run(
            user_id, command_name, key, command, operation, SubmissionData
        )

    async def result(self, user_id: UUID, assessment_id: UUID) -> ResultData:
        result = await self.repository.result(user_id, assessment_id)
        if result is None:
            raise AppError(ErrorCode.result_not_found, "测评结果尚未生成或不可访问", 404)
        latest = (
            await GuidanceRepository(self.repository.conn).latest(assessment_id)
            if result.is_member
            else None
        )
        if latest:
            result.calculation.guidance = latest
        return result

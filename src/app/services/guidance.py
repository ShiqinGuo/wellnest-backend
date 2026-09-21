from uuid import UUID

from app.domain.assessment import SubmitAssessmentCommand
from app.domain.enums import GuidanceEvent
from app.domain.guidance import Guidance
from app.domain.state_machine import GuidanceStateMachine
from app.errors import AppError, ErrorCode
from app.providers.typesafe import JevClient
from app.repositories.assessment import AssessmentRepository
from app.repositories.guidance import GuidanceRepository
from app.services.command import CommandService


class GuidanceService:
    def __init__(
        self,
        assessments: AssessmentRepository,
        repository: GuidanceRepository,
        commands: CommandService,
        jev: JevClient,
    ):
        self.assessments = assessments
        self.repository = repository
        self.commands = commands
        self.jev = jev

    async def retry(
        self, user_id: UUID, assessment_id: UUID, key: str, command: SubmitAssessmentCommand
    ) -> Guidance:
        name = f"guidance.retry:{assessment_id}"
        # Authorization is checked even on an idempotent replay.
        result = await self.assessments.result(user_id, assessment_id)
        if result is None:
            raise AppError(ErrorCode.result_not_found, "评估不存在", 404)
        if not result.is_member:
            raise AppError(ErrorCode.membership_required, "解锁后可查看行动建议", 403)
        replay = await self.commands.replay(user_id, name, key, command, Guidance)
        if replay:
            return replay

        async def current() -> Guidance:
            guidance = await self.repository.latest(assessment_id) or result.calculation.guidance
            if guidance is None:
                raise AppError(ErrorCode.guidance_not_retryable, "此历史评估没有行动建议")
            if guidance.revision != command.expected_version:
                raise AppError(ErrorCode.version_conflict, "行动建议已更新，请载入最新结果")
            GuidanceStateMachine.check(guidance.status, GuidanceEvent.retry)
            return guidance

        await current()
        snapshot = await self.repository.snapshot(assessment_id)
        await self.commands.release_connection()
        guidance = await self.jev.judge(snapshot)
        guidance.revision = command.expected_version + 1

        async def operation() -> Guidance:
            previous = await current()
            guidance.status = GuidanceStateMachine.transition(
                previous.status, GuidanceEvent.retry, guidance.status
            )
            await self.repository.append(assessment_id, guidance)
            return guidance

        return await self.commands.run(user_id, name, key, command, operation, Guidance)

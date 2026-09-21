from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from app.dependencies.auth import CommandKeyDep, IdentityDep
from app.dependencies.services import AssessmentServiceDep, GuidanceServiceDep
from app.presenters.assessment import AssessmentPresenter
from app.schemas.assessment import (
    AssessmentPatch,
    AssessmentView,
    CreateInput,
    SubmitInput,
    Submitted,
)
from app.schemas.result import FreeResult, Guidance, MemberResult

router = APIRouter(prefix="/api/assessments", tags=["assessments"])
AssessmentId = Annotated[UUID, Path(description="当前会话所属的测评 ID")]


@router.post("", status_code=HTTPStatus.CREATED)
async def create(
    payload: CreateInput, key: CommandKeyDep, me: IdentityDep, service: AssessmentServiceDep
) -> AssessmentView:
    return AssessmentPresenter.assessment(
        await service.create(me.user_id, key, payload.to_command())
    )


@router.get("/{assessment_id}")
async def get_assessment(
    assessment_id: AssessmentId, me: IdentityDep, service: AssessmentServiceDep
) -> AssessmentView:
    return AssessmentPresenter.assessment(await service.get(me.user_id, assessment_id))


@router.patch("/{assessment_id}")
async def update(
    assessment_id: AssessmentId,
    payload: AssessmentPatch,
    key: CommandKeyDep,
    me: IdentityDep,
    service: AssessmentServiceDep,
) -> AssessmentView:
    return AssessmentPresenter.assessment(
        await service.patch(me.user_id, assessment_id, key, payload.to_command())
    )


@router.post("/{assessment_id}/submit")
async def submit(
    assessment_id: AssessmentId,
    payload: SubmitInput,
    key: CommandKeyDep,
    me: IdentityDep,
    service: AssessmentServiceDep,
) -> Submitted:
    return AssessmentPresenter.submitted(
        await service.submit(me.user_id, assessment_id, key, payload.to_command())
    )


@router.get("/{assessment_id}/result", tags=["results"])
async def result(
    assessment_id: AssessmentId, me: IdentityDep, service: AssessmentServiceDep
) -> FreeResult | MemberResult:
    return AssessmentPresenter.result(await service.result(me.user_id, assessment_id))


@router.post("/{assessment_id}/guidance/retry", tags=["results"])
async def retry_guidance(
    assessment_id: AssessmentId,
    payload: SubmitInput,
    key: CommandKeyDep,
    me: IdentityDep,
    service: GuidanceServiceDep,
) -> Guidance:
    result = await service.retry(me.user_id, assessment_id, key, payload.to_command())
    return Guidance.model_validate(result.model_dump())

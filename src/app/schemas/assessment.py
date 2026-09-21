from datetime import datetime
from typing import Literal

from pydantic import Field

from app.domain.assessment import (
    Answers as AnswerData,
)
from app.domain.assessment import (
    CreateAssessmentCommand,
    Step,
    SubmitAssessmentCommand,
    UpdateAssessmentCommand,
    Version,
)
from app.domain.enums import AssessmentStatus
from app.schemas.base import APIModel
from app.schemas.result import PlanPreview


class Answers(AnswerData, APIModel):
    pass


class AssessmentPatch(APIModel):
    def to_command(self) -> UpdateAssessmentCommand:
        return UpdateAssessmentCommand.model_validate(self.model_dump(exclude_unset=True))

    expected_version: Version
    answers: Answers = Field(default_factory=Answers)
    resume_step_id: Step | None = None


class SubmitInput(APIModel):
    def to_command(self) -> SubmitAssessmentCommand:
        return SubmitAssessmentCommand.model_validate(self.model_dump(exclude_unset=True))

    expected_version: Version


class CreateInput(APIModel):
    def to_command(self) -> CreateAssessmentCommand:
        return CreateAssessmentCommand.model_validate(self.model_dump(exclude_unset=True))

    source_assessment_id: str | None = None
    start_new: bool = Field(default=False, strict=True)


class AssessmentView(APIModel):
    plan_preview: PlanPreview | None = None
    id: str
    status: AssessmentStatus
    version: int
    flow_version: str
    resume_step_id: Step
    answers: Answers
    completed_steps: list[str]
    missing_fields: list[str]
    updated_at: datetime


class Submitted(APIModel):
    result_id: str
    status: Literal[AssessmentStatus.completed]
    version: int

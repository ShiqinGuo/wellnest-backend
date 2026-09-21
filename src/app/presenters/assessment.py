from pydantic.alias_generators import to_camel

from app.domain.assessment import AssessmentData, ResultData, SubmissionData
from app.domain.flow import FIELD_FOR_STEP, applicable_steps
from app.domain.plan import build_plan
from app.domain.result_codes import ResultSummary
from app.schemas.assessment import Answers, AssessmentView, Submitted
from app.schemas.result import Calculation, FreeResult, MemberResult, PlanPreview


class AssessmentPresenter:
    @staticmethod
    def assessment(data: AssessmentData) -> AssessmentView:
        return AssessmentView(
            plan_preview=PlanPreview.model_validate(p.model_dump())
            if (p := build_plan(data.answers))
            else None,
            id=str(data.id),
            status=data.status,
            version=data.version,
            flow_version=data.flow_version,
            resume_step_id=data.resume_step_id,
            answers=Answers.model_validate(data.answers.model_dump()),
            completed_steps=[
                step
                for step, field in FIELD_FOR_STEP.items()
                if step in applicable_steps(data.answers, data.flow_version)
                and getattr(data.answers, field) is not None
            ],
            missing_fields=[to_camel(f) for f in data.answers.missing(data.flow_version)],
            updated_at=data.updated_at,
        )

    @staticmethod
    def submitted(data: SubmissionData) -> Submitted:
        return Submitted(result_id=str(data.result_id), status=data.status, version=data.version)

    @staticmethod
    def result(data: ResultData) -> FreeResult | MemberResult:
        preview = (
            PlanPreview.model_validate(data.calculation.plan_preview.model_dump())
            if data.calculation.plan_preview
            else None
        )
        summary = ResultSummary.personal_start
        if data.is_member:
            return MemberResult(
                plan_preview=preview,
                assessment_id=str(data.assessment_id),
                bmi=data.calculation.bmi,
                bmi_category=data.calculation.bmi_category,
                summary=summary,
                calculation=Calculation.model_validate(data.calculation.model_dump()),
            )
        return FreeResult(
            plan_preview=preview,
            assessment_id=str(data.assessment_id),
            bmi=data.calculation.bmi,
            bmi_category=data.calculation.bmi_category,
            summary=summary,
        )

from datetime import date
from typing import Literal

from pydantic import Field

from app.domain.assessment import Calculation as CalculationData
from app.domain.enums import ResultAccess
from app.domain.guidance import Guidance as GuidanceData
from app.domain.plan import PlanCard as PlanCardData
from app.domain.plan import PlanMessage as PlanMessageData
from app.domain.plan import PlanParams as PlanParamsData
from app.domain.plan import PlanPreview as PlanPreviewData
from app.domain.result_codes import BmiCategory, ResultSummary
from app.schemas.base import APIModel


class PlanParams(PlanParamsData, APIModel):
    pass


class PlanMessage(PlanMessageData, APIModel):
    params: PlanParams


class PlanCard(PlanCardData, APIModel):
    title: PlanMessage
    reason: list[PlanMessage]
    action: list[PlanMessage]


class PlanPreview(PlanPreviewData, APIModel):
    cards: list[PlanCard]
    preferences: list[PlanMessage]
    boundaries: list[PlanMessage]


class Guidance(GuidanceData, APIModel):
    pass


class ProjectionPoint(APIModel):
    date: date
    weight_kg: float


class Calculation(CalculationData, APIModel):
    plan_preview: PlanPreview | None = None
    guidance: Guidance | None = None
    projection: list[ProjectionPoint]


class FreeResult(APIModel):
    plan_preview: PlanPreview | None = None
    access: Literal[ResultAccess.free] = ResultAccess.free
    assessment_id: str
    bmi: float
    bmi_category: BmiCategory
    summary: ResultSummary
    locked_features: list[str] = Field(
        default_factory=lambda: ["suggestedKcal", "predictedGoalDate", "projection"]
    )


class MemberResult(APIModel):
    plan_preview: PlanPreview | None = None
    access: Literal[ResultAccess.member] = ResultAccess.member
    assessment_id: str
    bmi: float
    bmi_category: BmiCategory
    summary: ResultSummary
    calculation: Calculation

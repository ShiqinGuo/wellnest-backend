from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.enums import GuidanceStatus, RuleVersion
from app.domain.rules import JEV_RULES


class PlanFocus(StrEnum):
    movement_habit = "movement_habit"
    meal_routine = "meal_routine"
    consistency = "consistency"
    insufficient_context = "insufficient_context"


class Guidance(BaseModel):
    revision: int = Field(default=0, ge=0)
    status: GuidanceStatus
    rules_version: RuleVersion = JEV_RULES.version
    model: str | None = None
    focus: PlanFocus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    effort_score: float | None = Field(
        default=None, ge=JEV_RULES.effort_min, le=JEV_RULES.effort_max, allow_inf_nan=False
    )
    effort_confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    failure_code: str | None = None

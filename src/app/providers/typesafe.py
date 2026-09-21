import asyncio
import math
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.domain.assessment import CompleteAnswers
from app.domain.enums import (
    Activity,
    Barrier,
    DailyActivity,
    Energy,
    Experience,
    FoodHabit,
    Goal,
    GuidanceStatus,
    Limitation,
    MealRhythm,
    SecondaryGoal,
    Sleep,
    TimeWindow,
)
from app.domain.guidance import Guidance, PlanFocus
from app.domain.rules import JEV_RULES

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
API_URL = "https://api.typesafe.ai/v1/systemone"


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: PlanFocus
    confidence: Probability
    probabilities: dict[PlanFocus, Probability]

    @model_validator(mode="after")
    def valid_distribution(self):
        if set(self.probabilities) != set(PlanFocus):
            raise ValueError("Unexpected choices")
        if not math.isclose(
            sum(self.probabilities.values()), 1, abs_tol=JEV_RULES.probability_tolerance
        ):
            raise ValueError("Invalid probabilities")
        if self.probabilities[self.choice] < max(self.probabilities.values()):
            raise ValueError("Choice contradicts probabilities")
        return self


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float = Field(
        ge=JEV_RULES.effort_min, le=JEV_RULES.effort_max, allow_inf_nan=False, strict=True
    )
    confidence: Probability


class JevAnswers(BaseModel):
    focus: ChoiceAnswer
    effort: ScoreAnswer


class JevResponse(BaseModel):
    model: str = Field(min_length=1)
    answers: JevAnswers


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str]


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str]


class Questions(BaseModel):
    focus: ChoiceQuestion
    effort: ScoreQuestion


class GuidanceContext(BaseModel):
    goal: Goal
    activity: Activity
    secondary_goals: list[SecondaryGoal] | None = None
    experience: Experience | None = None
    daily_activity: DailyActivity | None = None
    limitations: list[Limitation] | None = None
    sleep: Sleep | None = None
    energy: Energy | None = None
    meal_rhythm: MealRhythm | None = None
    food_habits: list[FoodHabit] | None = None
    barrier: Barrier | None = None
    time_window: TimeWindow | None = None
    relative_target_change: float


class JevRequest(BaseModel):
    model: str = JEV_RULES.model
    state: GuidanceContext
    questions: Questions


QUESTIONS = Questions(
    focus=ChoiceQuestion(
        instructions="Select one non-medical habit focus for this adult wellness plan. "
        "Weigh activity and relative target change together. Select the most useful first "
        "habit; overlapping candidates are allowed. Abstain when context is insufficient. "
        "Do not diagnose, prescribe, or infer motivation from demographics. "
        "Use the supplied lifestyle answers. Do not infer meal problems from weight change. "
        "Respect stated physical limitations and time constraints. If lifestyle context is "
        "missing, abstain from meal-routine judgments.",
        criteria={
            "movement_habit": "Building comfortable regular movement seems the useful first step.",
            "meal_routine": "A more consistent meal routine seems the useful first step.",
            "consistency": "Sustaining and reviewing existing habits seems the useful first step.",
            "insufficient_context": "No clear fit or insufficient information.",
        },
    ),
    effort=ScoreQuestion(
        instructions="Estimate relative habit-change effort from stated goal, activity, and "
        "relative target weight change. Not medical risk or success probability.",
        criteria=[
            "Maintain existing habits or very small change",
            "Moderate habit adjustment",
            "Substantial sustained habit adjustment",
        ],
    ),
)


class JevTransportError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class JsonTransport(Protocol):
    async def post(self, body: str) -> str: ...


class HttpxTransport:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def post(self, body: str) -> str:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=JEV_RULES.timeout_seconds) as client:
                response = await client.post(
                    API_URL,
                    content=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError:
            raise JevTransportError("transport_error") from None
        if response.status_code != 200:
            raise JevTransportError(f"upstream_{response.status_code}")
        return response.text


class WorkersTransport:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def post(self, body: str) -> str:
        from workers import fetch

        try:
            response = await fetch(
                API_URL,
                method="POST",
                body=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            if response.status != 200:
                raise JevTransportError(f"upstream_{response.status}")
            return await response.text()
        except OSError:
            raise JevTransportError("transport_error") from None


class JevClient:
    def __init__(
        self, transport: JsonTransport | None, *, timeout_seconds: float = JEV_RULES.timeout_seconds
    ):
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def judge(self, answers: CompleteAnswers) -> Guidance:
        if self.transport is None:
            return Guidance(status=GuidanceStatus.disabled)
        request = JevRequest(
            state=GuidanceContext(
                secondary_goals=answers.secondary_goals,
                experience=answers.experience,
                daily_activity=answers.daily_activity,
                limitations=answers.limitations,
                sleep=answers.sleep,
                energy=answers.energy,
                meal_rhythm=answers.meal_rhythm,
                food_habits=answers.food_habits,
                barrier=answers.barrier,
                time_window=answers.time_window,
                goal=answers.goal,
                activity=answers.activity,
                relative_target_change=(answers.target_weight_kg - answers.weight_kg)
                / answers.weight_kg,
            ),
            questions=QUESTIONS,
        )
        try:
            # One bounded attempt; no stacked retries or invented AI result on failure.
            async with asyncio.timeout(self.timeout_seconds):
                raw = await self.transport.post(request.model_dump_json())
            response = JevResponse.model_validate_json(raw)
        except TimeoutError:
            return Guidance(status=GuidanceStatus.unavailable, failure_code="timeout")
        except JevTransportError as exc:
            return Guidance(status=GuidanceStatus.unavailable, failure_code=exc.code)
        except ValidationError:
            return Guidance(status=GuidanceStatus.unavailable, failure_code="invalid_response")
        focus, effort = response.answers.focus, response.answers.effort
        certain = (
            focus.confidence >= JEV_RULES.minimum_confidence
            and focus.choice != PlanFocus.insufficient_context
        )
        return Guidance(
            status=GuidanceStatus.ready if certain else GuidanceStatus.uncertain,
            model=response.model,
            focus=focus.choice if certain else None,
            confidence=focus.confidence,
            effort_score=effort.score
            if effort.confidence >= JEV_RULES.minimum_confidence
            else None,
            effort_confidence=effort.confidence,
        )

from app.domain.enums import SubscriptionStatus
from app.schemas.assessment import AssessmentView
from app.schemas.base import APIModel


class SessionCreated(APIModel):
    session_id: str


class SessionView(SessionCreated):
    subscription_status: SubscriptionStatus
    assessment: AssessmentView | None

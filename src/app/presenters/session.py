from app.domain.enums import SubscriptionStatus
from app.domain.session import SessionData
from app.presenters.assessment import AssessmentPresenter
from app.schemas.session import SessionView


class SessionPresenter:
    @staticmethod
    def session(data: SessionData) -> SessionView:
        return SessionView(
            session_id=str(data.session_id),
            subscription_status=SubscriptionStatus.active
            if data.is_member
            else SubscriptionStatus.inactive,
            assessment=AssessmentPresenter.assessment(data.assessment) if data.assessment else None,
        )

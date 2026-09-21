from dataclasses import dataclass
from uuid import UUID

from app.domain.assessment import AssessmentData


@dataclass(frozen=True)
class IdentityData:
    session_id: UUID
    user_id: UUID


@dataclass(frozen=True)
class CreatedSessionData:
    session_id: UUID
    token: str | None = None


@dataclass(frozen=True)
class SessionData:
    session_id: UUID
    is_member: bool
    assessment: AssessmentData | None

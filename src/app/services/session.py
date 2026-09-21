import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.session import CreatedSessionData, IdentityData, SessionData
from app.errors import AppError, ErrorCode
from app.repositories.assessment import AssessmentRepository
from app.repositories.payment import PaymentRepository
from app.repositories.session import SessionRepository
from app.settings import RUNTIME

SESSION_MAX_AGE = RUNTIME.session_lifetime_days * RUNTIME.seconds_per_day


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        assessments: AssessmentRepository,
        payments: PaymentRepository,
    ):
        self.repository = repository
        self.assessments = assessments
        self.payments = payments

    async def authenticate(self, token: str | None) -> IdentityData:
        if not token or len(token) > RUNTIME.max_token_length:
            raise AppError(ErrorCode.session_required)
        identity = await self.repository.find(digest(token))
        if identity is None:
            raise AppError(ErrorCode.session_expired)
        return identity

    async def start(self, existing_token: str | None) -> CreatedSessionData:
        if existing_token and len(existing_token) <= RUNTIME.max_token_length:
            existing = await self.repository.find(digest(existing_token))
            if existing:
                return CreatedSessionData(existing.session_id)
        token = secrets.token_urlsafe(RUNTIME.token_entropy_bytes)
        identity = IdentityData(session_id=uuid4(), user_id=uuid4())
        async with self.repository.transaction():
            await self.repository.create(
                identity,
                digest(token),
                datetime.now(UTC) + timedelta(days=RUNTIME.session_lifetime_days),
            )
        return CreatedSessionData(identity.session_id, token)

    async def current(self, identity: IdentityData) -> SessionData:
        return SessionData(
            session_id=identity.session_id,
            is_member=await self.payments.is_member(identity.user_id),
            assessment=await self.assessments.current(identity.user_id),
        )

import os
from typing import Annotated

from fastapi import Depends, Request

from app.dependencies.database import DatabaseDep
from app.dependencies.payments import PaymentSettingsDep
from app.providers.typesafe import HttpxTransport, JevClient, WorkersTransport
from app.repositories.assessment import AssessmentRepository
from app.repositories.command import CommandRepository
from app.repositories.guidance import GuidanceRepository
from app.repositories.outbox import OutboxRepository
from app.repositories.payment import PaymentRepository
from app.repositories.session import SessionRepository
from app.services.assessment import AssessmentService
from app.services.command import CommandService
from app.services.guidance import GuidanceService
from app.services.payment import PaymentService
from app.services.session import SessionService


async def get_commands(db: DatabaseDep) -> CommandService:
    return CommandService(CommandRepository(db))


CommandServiceDep = Annotated[CommandService, Depends(get_commands)]


async def get_jev(request: Request) -> JevClient:
    env = request.scope.get("env")
    api_key = (
        getattr(env, "TYPESAFE_API_KEY", None) if env is not None else os.getenv("TYPESAFE_API_KEY")
    )
    if not api_key:
        return JevClient(None)
    transport = WorkersTransport(str(api_key)) if env is not None else HttpxTransport(api_key)
    return JevClient(transport)


JevClientDep = Annotated[JevClient, Depends(get_jev)]


async def get_assessments(
    db: DatabaseDep, commands: CommandServiceDep, jev: JevClientDep
) -> AssessmentService:
    return AssessmentService(AssessmentRepository(db), commands, jev, GuidanceRepository(db))


async def get_payments(
    db: DatabaseDep, commands: CommandServiceDep, settings: PaymentSettingsDep
) -> PaymentService:
    return PaymentService(
        PaymentRepository(db),
        AssessmentRepository(db),
        commands,
        settings,
        OutboxRepository(db),
        commands.repository,
    )


async def get_sessions(db: DatabaseDep) -> SessionService:
    return SessionService(SessionRepository(db), AssessmentRepository(db), PaymentRepository(db))


AssessmentServiceDep = Annotated[AssessmentService, Depends(get_assessments)]
PaymentServiceDep = Annotated[PaymentService, Depends(get_payments)]
SessionServiceDep = Annotated[SessionService, Depends(get_sessions)]


async def get_guidance(
    db: DatabaseDep, commands: CommandServiceDep, jev: JevClientDep
) -> GuidanceService:
    return GuidanceService(AssessmentRepository(db), GuidanceRepository(db), commands, jev)


GuidanceServiceDep = Annotated[GuidanceService, Depends(get_guidance)]

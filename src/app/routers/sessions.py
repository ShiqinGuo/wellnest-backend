from fastapi import APIRouter, Request, Response

from app.dependencies.auth import SESSION_COOKIE, IdentityDep
from app.dependencies.services import SessionServiceDep
from app.presenters.session import SessionPresenter
from app.schemas.session import SessionCreated, SessionView
from app.services.session import SESSION_MAX_AGE
from app.settings import runtime_value

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/sessions", status_code=201)
async def start_session(
    request: Request, response: Response, service: SessionServiceDep
) -> SessionCreated:
    created = await service.start(request.cookies.get(SESSION_COOKIE))
    if created.token:
        response.set_cookie(
            SESSION_COOKIE,
            created.token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=runtime_value(
                request.scope.get("env"), "WELLNEST_SECURE_COOKIES", "true"
            ) == "true",
            samesite="lax",
        )
    return SessionCreated(session_id=str(created.session_id))


@router.get("/session")
async def session(me: IdentityDep, service: SessionServiceDep) -> SessionView:
    return SessionPresenter.session(await service.current(me))

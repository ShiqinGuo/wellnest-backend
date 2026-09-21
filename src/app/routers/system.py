from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies.database import DatabaseDep
from app.repositories.health import HealthRepository

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]


async def check_database(db: DatabaseDep) -> None:
    await HealthRepository(db).check_database()


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready")
async def ready(checked: Annotated[None, Depends(check_database)]) -> HealthResponse:
    return HealthResponse(status="ready")

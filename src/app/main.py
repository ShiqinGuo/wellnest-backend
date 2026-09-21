import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.errors import AppError
from app.exception_handlers import app_error, validation_error
from app.middleware import RequestPolicy
from app.routers import assessments, internal_payments, payments, sessions, system
from app.telemetry import configure_telemetry


def create_app() -> FastAPI:
    application = FastAPI(title="Wellnest API", version="0.2.0")
    application.add_middleware(RequestPolicy)
    origin = os.getenv("WELLNEST_ORIGIN")
    if origin:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[origin],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["Content-Type", "Idempotency-Key", "Authorization"],
        )
    application.add_exception_handler(AppError, app_error)
    application.add_exception_handler(RequestValidationError, validation_error)
    for router in (
        system.router,
        sessions.router,
        assessments.router,
        payments.router,
        internal_payments.router,
    ):
        application.include_router(router)
    configure_telemetry(application)
    return application


app = create_app()

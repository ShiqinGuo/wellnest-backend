from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import AppError


async def app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "requestId": request.state.request_id,
            }
        },
        status_code=exc.status,
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Never echo submitted values (health data or credentials) in error payloads.
    issues = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(
        {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请检查填写的信息",
                "details": {"issues": issues},
                "requestId": request.state.request_id,
            }
        },
        status_code=422,
    )

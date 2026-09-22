from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import AppError, ErrorCode


def error_response(error: AppError, request_id: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "requestId": request_id,
            }
        },
        status_code=error.status,
    )


async def app_error(request: Request, exc: AppError) -> JSONResponse:
    request.state.error_code = exc.code
    request.state.error_details = exc.details
    return error_response(exc, request.state.request_id)


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Return machine-readable field errors, never input values or exception messages.
    issues = [{"field": ".".join(map(str, e["loc"])), "code": e["type"]} for e in exc.errors()]
    request.state.error_code = ErrorCode.validation_error
    request.state.error_details = {"issues": issues}
    return error_response(
        AppError(ErrorCode.validation_error, details={"issues": issues}), request.state.request_id
    )

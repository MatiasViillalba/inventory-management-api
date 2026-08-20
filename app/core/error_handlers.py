"""Global exception handlers translating domain exceptions to HTTP responses.

Centralizes the mapping from app.core.exceptions.AppException subclasses
to HTTP status codes in one place, so service and repository code can
raise plain domain exceptions without importing FastAPI, and endpoints
don't need to repeat a try/except HTTPException block per route. A
catch-all handler also ensures truly unexpected exceptions still
produce a well-formed JSON error response instead of leaking a raw
traceback to the client.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AppException,
    ConflictError,
    InactiveResourceError,
    InsufficientStockError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

_STATUS_CODE_BY_EXCEPTION: dict[type[AppException], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InsufficientStockError: status.HTTP_409_CONFLICT,
    InactiveResourceError: status.HTTP_409_CONFLICT,
    ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Translate a domain exception into a JSON error response.

    Args:
        request: The incoming request that triggered the exception.
        exc: The domain exception raised by a service or repository.

    Returns:
        JSONResponse: A `{"detail": ...}` body with the status code
        mapped for this exception type (400 if the type is unmapped).
    """
    status_code = _STATUS_CODE_BY_EXCEPTION.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=status_code, content={"detail": exc.message})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for exceptions with no explicit mapping.

    Logs the full traceback server-side so the incident is diagnosable,
    while returning a generic body to the client so internal details
    (stack traces, query text) are never exposed over the API.

    Args:
        request: The incoming request that triggered the exception.
        exc: The unexpected exception.

    Returns:
        JSONResponse: A generic 500 error body.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
        extra={
            "request_id": request_id,
            "http_method": request.method,
            "http_path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the application's global exception handlers.

    Args:
        app: The FastAPI application instance to configure.
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

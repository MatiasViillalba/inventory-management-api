"""Application entry point.

This module creates and configures the FastAPI application instance.
It is intentionally kept minimal: routers, middlewares, and exception
handlers are wired in here as they are introduced in later commits,
following the Clean Architecture principle of keeping the entry point
free of business logic.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware

settings = get_settings()
configure_logging()

app = FastAPI(
    title=settings.project_name,
    debug=settings.debug,
    version="0.1.0",
)

# Middlewares run in the reverse order they're added, so SecurityHeadersMiddleware
# and CORSMiddleware (added last) wrap the outermost layer of every response,
# including those from RequestLoggingMiddleware and the route handlers.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_v1_prefix)

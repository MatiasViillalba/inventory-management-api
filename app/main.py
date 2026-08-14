"""Application entry point.

This module creates and configures the FastAPI application instance.
It is intentionally kept minimal: routers, middlewares, and exception
handlers are wired in here as they are introduced in later commits,
following the Clean Architecture principle of keeping the entry point
free of business logic.
"""

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.project_name,
    debug=settings.debug,
    version="0.1.0",
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

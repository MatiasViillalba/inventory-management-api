"""Application entry point.

This module creates and configures the FastAPI application instance.
It is intentionally kept minimal: routers, middlewares, and exception
handlers are wired in here as they are introduced in later commits,
following the Clean Architecture principle of keeping the entry point
free of business logic.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
from app.core.scheduler import start_scheduler, stop_scheduler
from app.events.publisher import get_event_publisher
from app.websockets.listeners import register_websocket_listeners
from app.websockets.manager import get_connection_manager
from app.websockets.pubsub import get_redis_broadcaster, relay_to_local_clients

settings = get_settings()
configure_logging()
register_websocket_listeners(get_event_publisher(), get_redis_broadcaster())

API_DESCRIPTION = """
Real-time inventory control across multiple warehouses, with automatic
low-stock alerting, an immutable audit trail, and asynchronous
reporting.

### Architecture highlights
- **CQRS on the Inventory aggregate** — reads (`InventoryQueryService`)
  and stock-mutating writes (`InventoryCommandService`) are separate
  classes, so the write side's row-locking and audit-trail concerns
  never leak into the read path.
- **Event-driven side effects** — stock movements publish domain events
  (`app/events`) that alerting and WebSocket broadcasting react to,
  instead of being called inline from the request handler.
- **Background processing** — Celery handles low-stock emails and CSV
  report generation off the request/response cycle; Celery Beat runs a
  periodic reconciliation sweep as a safety net on top of the
  event-driven path.

Every error response below follows one shape: `{"detail": "..."}`.
"""

_OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Liveness/readiness check used by orchestrators and uptime monitors.",
    },
    {
        "name": "Warehouses",
        "description": "Physical/logical storage locations that hold inventory.",
    },
    {
        "name": "Products",
        "description": "Catalog items that are tracked and stored as inventory.",
    },
    {
        "name": "Inventory",
        "description": "Current stock levels, and the single endpoint that mutates "
        "them by recording a movement.",
    },
    {
        "name": "Movements",
        "description": "Read-only audit trail of every stock change (add, remove, transfer).",
    },
    {
        "name": "Alerts",
        "description": "Low-stock/out-of-stock notifications raised automatically "
        "from inventory activity.",
    },
    {
        "name": "Reports",
        "description": "Aggregate, cross-warehouse figures computed on demand.",
    },
    {
        "name": "WebSockets",
        "description": "Real-time push feed for inventory activity — see the `/ws` "
        "route for the connection contract.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the Redis pub/sub relay loop for the app process's lifetime.

    Started here rather than at import time because it needs a running
    event loop, which only exists once Uvicorn starts serving — and it
    must be cancelled cleanly on shutdown so the process doesn't hang
    waiting on an open Redis subscription.

    Args:
        app: The FastAPI application instance (required by the
            lifespan protocol, unused here).

    Yields:
        None. Control returns to FastAPI once the relay task is
        running, and resumes here on shutdown to tear it down.
    """
    relay_task = asyncio.create_task(
        relay_to_local_clients(get_redis_broadcaster(), get_connection_manager())
    )
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        relay_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay_task
        await get_redis_broadcaster().close()


app = FastAPI(
    title=settings.project_name,
    description=API_DESCRIPTION,
    debug=settings.debug,
    version="0.1.0",
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,
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


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect the API root to the interactive Swagger UI docs.

    Excluded from the OpenAPI schema itself since it isn't a resource
    of the API — just a convenience for a human opening the base URL
    in a browser.

    Returns:
        RedirectResponse: A redirect to /docs.
    """
    return RedirectResponse(url="/docs")

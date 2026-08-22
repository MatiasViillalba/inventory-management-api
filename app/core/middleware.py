"""Request/response logging middleware.

Logs one line per request with a correlation id, method, path, status
code, and duration, so a single request's lifecycle can be traced
through the logs even under concurrent traffic. Request/response
bodies are intentionally never logged here — they can carry sensitive
data (passwords, tokens) and belong to a dedicated audit trail, not
free-text logs.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs each request's method, path, status code, and duration.

    A unique request id is generated per request, stored on
    `request.state.request_id` for use by other components (e.g. error
    handlers could include it in a response body), and echoed back to
    the client via the X-Request-ID response header to correlate
    client-side reports with server-side logs.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Time the request, log the outcome, and tag the response.

        Args:
            request: The incoming request.
            call_next: The next handler in the middleware chain.

        Returns:
            Response: The response produced downstream, with an added
            X-Request-ID header.
        """
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s -> %d (%.1fms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
            extra={
                "request_id": request_id,
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
            },
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard security-related headers to every response.

    Covers the baseline OWASP secure-headers recommendations relevant
    to a JSON API: this app has no HTML views, so headers aimed at
    script/style injection (CSP) are set with a locked-down default
    rather than omitted, and browser-specific protections (framing,
    MIME sniffing) are enabled unconditionally. The locked-down CSP is
    skipped for FastAPI's own docs pages, which load Swagger UI/ReDoc
    assets from a CDN and would otherwise be blocked by it.
    """

    _DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Attach security headers to the downstream response.

        Args:
            request: The incoming request.
            call_next: The next handler in the middleware chain.

        Returns:
            Response: The response produced downstream, with security
            headers added.
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        if request.url.path not in self._DOCS_PATHS:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
        return response

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
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

"""Application-wide structured logging configuration.

Configures the root logger once at startup so every module's
`logging.getLogger(__name__)` call (error handlers, middleware,
services) emits consistently formatted output, without each module
needing to configure logging itself.

Two output formats are supported. In development, logs are rendered as
a single readable line, since a human is watching a terminal. In every
other environment, logs are rendered as one JSON object per line,
since they're expected to be shipped to a log aggregator (CloudWatch,
Datadog, ELK, ...) that indexes structured fields rather than grepping
free text. Any caller can add fields to a specific log line via the
standard `extra={...}` kwarg (see app.core.middleware's request_id, or
error_handlers' unhandled-exception logging) — JSONFormatter picks up
whatever is there without needing to know the field names in advance.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings

# Every attribute a bare LogRecord carries, computed once from a
# throwaway instance. Anything on a real record beyond this set came
# from a caller's `extra={...}` kwarg and should be surfaced as its
# own field in the JSON output, rather than left inaccessible.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
)


class JSONFormatter(logging.Formatter):
    """Renders each LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a LogRecord to a JSON string.

        Args:
            record: The log record to format.

        Returns:
            str: A single-line JSON object representing the record.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure the root logger's level, format, and output handler.

    Uses DEBUG in development for verbose diagnostics and INFO in
    other environments to avoid flooding production logs. Safe to call
    more than once: logging.basicConfig is a no-op if handlers are
    already configured on the root logger.
    """
    settings = get_settings()
    level = logging.DEBUG if settings.environment == "development" else logging.INFO

    handler = logging.StreamHandler()
    if settings.environment == "development":
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
    else:
        handler.setFormatter(JSONFormatter())

    logging.basicConfig(level=level, handlers=[handler])

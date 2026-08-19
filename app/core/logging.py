"""Application-wide logging configuration.

Configures the root logger once at startup so every module's
`logging.getLogger(__name__)` call (error handlers, middleware,
services) emits consistently formatted output, without each module
needing to configure logging itself.
"""

import logging

from app.core.config import get_settings


def configure_logging() -> None:
    """Configure the root logger's level and output format.

    Uses DEBUG in development for verbose diagnostics and INFO in
    other environments to avoid flooding production logs. Safe to call
    more than once: logging.basicConfig is a no-op if handlers are
    already configured on the root logger.
    """
    settings = get_settings()
    level = logging.DEBUG if settings.environment == "development" else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

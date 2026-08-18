"""In-process implementation of the domain event publisher.

InProcessEventPublisher is the concrete EventPublisher used by this
application: it dispatches events to handlers within the same process
via asyncio, rather than through an external broker. This keeps the
event-driven flow simple while the app is a single service; swapping in
a Redis- or Celery-backed publisher later only requires implementing
the same EventPublisher interface, since callers depend on that
abstraction, not this class.
"""

import asyncio
import logging
from collections import defaultdict

from app.events.base import DomainEvent, EventHandler, EventPublisher

logger = logging.getLogger(__name__)


class InProcessEventPublisher(EventPublisher):
    """Dispatches events to in-process async handlers, keyed by event_type.

    Attributes:
        _handlers: Maps each event_type name to the list of handlers
            subscribed to it.
    """

    def __init__(self) -> None:
        """Initialize the publisher with no subscribers registered."""
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler to run whenever a matching event is published.

        Args:
            event_type: The event_type name to listen for.
            handler: An async callable invoked with each matching event.
        """
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Publish a single event to every subscriber of its type.

        Handlers run concurrently. A handler that raises is logged and
        does not prevent the other handlers for the same event from
        running, nor does it propagate back to the caller: publishing
        is a side effect of a business operation that already
        committed, and a broken subscriber must not appear to roll that
        operation back.

        Args:
            event: The event instance to publish.
        """
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            return

        results = await asyncio.gather(
            *(handler(event) for handler in handlers), return_exceptions=True
        )
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                logger.exception(
                    "Event handler '%s' failed while handling '%s' (event_id=%s).",
                    getattr(handler, "__qualname__", repr(handler)),
                    event.event_type,
                    event.event_id,
                    exc_info=result,
                )


_event_publisher = InProcessEventPublisher()


def get_event_publisher() -> EventPublisher:
    """Return the process-wide EventPublisher singleton.

    A single shared instance is required, unlike get_db's per-request
    session, so that subscriptions registered once at application
    startup remain in effect for every subsequent request.

    Returns:
        The shared InProcessEventPublisher instance.
    """
    return _event_publisher

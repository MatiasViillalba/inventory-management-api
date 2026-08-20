"""Celery task for periodic low-stock alert reconciliation.

AlertService.evaluate_stock_level already runs synchronously after
every stock mutation (see InventoryCommandService), so alerts are
correct in the common case the moment a movement is recorded. This
task exists as a self-healing sweep on top of that: it re-evaluates
every inventory record on a schedule so alert state also recovers from
out-of-band changes, such as a manual database correction, a
threshold edit, or a missed event.
"""

import asyncio
import logging

from app.core.session import AsyncSessionLocal
from app.events.publisher import get_event_publisher
from app.repositories.inventory import InventoryRepository
from app.services.alert import AlertService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_BATCH_SIZE = 200


@celery_app.task(name="app.tasks.alerts.check_low_stock_levels")
def check_low_stock_levels() -> dict[str, int]:
    """Re-evaluate every inventory record against its low-stock threshold.

    Entry point invoked by Celery Beat on a schedule (wired up in a
    later commit). Delegates to an async implementation since the
    entire data-access layer is async-only; Celery workers run tasks
    synchronously, so `asyncio.run` drives the coroutine to completion
    on a dedicated event loop for this task execution.

    Returns:
        dict[str, int]: A summary with the number of inventory records
        evaluated and the number currently in an active alert state.
    """
    return asyncio.run(_check_low_stock_levels())


async def _check_low_stock_levels() -> dict[str, int]:
    """Page through all inventory and reconcile alert state for each.

    Opens a database session scoped to this task run rather than
    reusing any FastAPI request-scoped session, since this code path
    is triggered by Celery Beat, not an HTTP request.

    Returns:
        dict[str, int]: A summary with `evaluated` and `alerts_active` counts.
    """
    evaluated = 0
    alerts_active = 0

    async with AsyncSessionLocal() as session:
        repository = InventoryRepository(session)
        alert_service = AlertService(session, get_event_publisher())

        skip = 0
        while True:
            batch = await repository.list_all(skip=skip, limit=_BATCH_SIZE)
            if not batch:
                break

            for inventory in batch:
                evaluated += 1
                alert = await alert_service.evaluate_stock_level(inventory)
                if alert is not None:
                    alerts_active += 1

            skip += _BATCH_SIZE

    logger.info(
        "Low-stock sweep completed: evaluated=%d alerts_active=%d",
        evaluated,
        alerts_active,
    )
    return {"evaluated": evaluated, "alerts_active": alerts_active}

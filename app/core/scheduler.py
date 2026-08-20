"""In-process periodic job scheduler (APScheduler).

Distinct from Celery Beat (see app/tasks/celery_app.py's
beat_schedule): Celery Beat triggers real Celery tasks, executed by a
separate worker process, for jobs that touch the database and must
keep running even if this API process restarts (e.g. the low-stock
sweep). APScheduler here runs lightweight jobs directly on the FastAPI
process's own event loop, for work that only makes sense while this
specific process is alive — this process's own in-memory WebSocket
connections aren't visible to a Celery worker at all, so a job that
manages them has no business being a Celery task.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.websockets.manager import get_connection_manager

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 30

scheduler = AsyncIOScheduler(timezone="UTC")


async def _broadcast_heartbeat() -> None:
    """Send a lightweight heartbeat to every locally connected WebSocket client.

    Serves two purposes: it keeps otherwise-idle WebSocket connections
    alive through proxies and load balancers that close connections
    after a period of inactivity, and it opportunistically prunes dead
    ones, since ConnectionManager.broadcast already drops any
    connection it fails to send to rather than waiting for it to fail
    again on the next real event.
    """
    await get_connection_manager().broadcast({"event_type": "heartbeat"})
    logger.debug("Broadcast WebSocket heartbeat.")


def start_scheduler() -> None:
    """Register scheduled jobs and start the scheduler.

    Safe to call more than once per process: a job id is only added if
    it isn't already scheduled, and starting an already-running
    scheduler is a no-op in APScheduler. Called from app/main.py's
    lifespan on startup.
    """
    if scheduler.get_job("websocket_heartbeat") is None:
        scheduler.add_job(
            _broadcast_heartbeat,
            trigger="interval",
            seconds=_HEARTBEAT_INTERVAL_SECONDS,
            id="websocket_heartbeat",
        )
    if not scheduler.running:
        scheduler.start()


def stop_scheduler() -> None:
    """Stop the scheduler without waiting for any in-flight job to finish.

    Called from app/main.py's lifespan on shutdown, after the app has
    already stopped accepting new connections, so an in-progress
    heartbeat broadcast is safe to abandon.
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)

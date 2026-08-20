"""Celery application factory and configuration.

This module creates the single Celery application instance used by
every background task in the project. It is intentionally isolated
from the FastAPI app (`app.main`) so the Celery worker process can
import it without booting the web server, and vice versa.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "inventory_management_api",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Task modules are listed explicitly rather than via
    # autodiscover_tasks, since that helper looks for a `tasks.py`
    # submodule inside each package and would miss the flat,
    # single-purpose modules used here (alerts.py, notifications.py,
    # reports.py). Extended in later commits as new task modules land.
    include=["app.tasks.alerts", "app.tasks.notifications"],
)

celery_app.conf.update(
    # --- Serialization ---
    # Celery defaults to pickle, which can execute arbitrary code when
    # deserializing untrusted payloads. JSON is restricted to plain data
    # and is safe to use across process boundaries.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # --- Timezone ---
    timezone="UTC",
    enable_utc=True,
    # --- Task execution ---
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # --- Result backend ---
    result_expires=3600,
)

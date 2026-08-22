"""Celery task lifecycle monitoring via signal handlers.

Structured logging (see app/core/logging.py) only captures what a task
logs internally; it says nothing about task-level outcomes — how long
a task ran, whether it succeeded, failed, or was retried — unless
every task remembers to log that itself. Subscribing to Celery's
built-in signals here instead makes outcome logging automatic and
consistent across every current and future task, without each one
repeating the same timing/logging boilerplate. Importing this module
(see app/tasks/celery_app.py's `include`) is enough to activate it —
the `@signals.*.connect` decorators register the handlers as a side
effect of import.
"""

import logging
import time
from typing import Any

from celery import signals

logger = logging.getLogger("app.tasks.monitoring")

# Keyed by task_id, so a task's duration can be computed in
# task_postrun without threading a start time through every task's own
# signature. Entries are always popped on completion, so this never
# grows across a long-running worker process.
_start_times: dict[str, float] = {}


@signals.task_prerun.connect
def _on_task_prerun(task_id: str | None = None, task: Any = None, **_: Any) -> None:
    """Record a task's start time and log that it began.

    Args:
        task_id: The unique id of this task execution.
        task: The task instance about to run.
        **_: Additional signal arguments Celery may pass, ignored.
    """
    if task_id is not None:
        _start_times[task_id] = time.perf_counter()
    logger.info(
        "Task started: %s",
        getattr(task, "name", "<unknown>"),
        extra={"task_name": getattr(task, "name", None), "task_id": task_id},
    )


@signals.task_postrun.connect
def _on_task_postrun(
    task_id: str | None = None, task: Any = None, state: str | None = None, **_: Any
) -> None:
    """Log a task's completion, including its duration and final state.

    Args:
        task_id: The unique id of this task execution.
        task: The task instance that ran.
        state: The task's final state (e.g. "SUCCESS", "FAILURE").
        **_: Additional signal arguments Celery may pass, ignored.
    """
    start_time = _start_times.pop(task_id, None) if task_id is not None else None
    duration_ms = (
        round((time.perf_counter() - start_time) * 1000, 1) if start_time else None
    )
    logger.info(
        "Task finished: %s (%s)",
        getattr(task, "name", "<unknown>"),
        state,
        extra={
            "task_name": getattr(task, "name", None),
            "task_id": task_id,
            "task_state": state,
            "duration_ms": duration_ms,
        },
    )


@signals.task_failure.connect
def _on_task_failure(
    task_id: str | None = None,
    sender: Any = None,
    exception: BaseException | None = None,
    einfo: Any = None,
    **_: Any,
) -> None:
    """Log a task failure at ERROR level, with its exception traceback.

    Args:
        task_id: The unique id of this task execution.
        sender: The task class that failed.
        exception: The exception the task raised.
        einfo: Celery's ExceptionInfo wrapper, used for the traceback.
        **_: Additional signal arguments Celery may pass, ignored.
    """
    logger.error(
        "Task failed: %s (%s)",
        getattr(sender, "name", "<unknown>"),
        exception,
        extra={"task_name": getattr(sender, "name", None), "task_id": task_id},
        exc_info=einfo,
    )


@signals.task_retry.connect
def _on_task_retry(
    request: Any = None, sender: Any = None, reason: Any = None, **_: Any
) -> None:
    """Log that a task is being retried, and why.

    Args:
        request: The task request being retried, carries its id.
        sender: The task class being retried.
        reason: The exception or message that triggered the retry.
        **_: Additional signal arguments Celery may pass, ignored.
    """
    logger.warning(
        "Task retrying: %s (%s)",
        getattr(sender, "name", "<unknown>"),
        reason,
        extra={
            "task_name": getattr(sender, "name", None),
            "task_id": getattr(request, "id", None),
        },
    )

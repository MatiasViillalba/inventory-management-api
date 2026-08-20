"""Endpoints for inventory alerts.

Alerts are created and escalated internally by AlertService in
reaction to stock-level changes (see AlertService.evaluate_stock_level,
invoked from the inventory write side) — clients never create an alert
directly. This module exposes read routes over the alert history and
the one client-triggered mutation: manually resolving an active alert.

Domain exceptions raised by the service (NotFoundError, ConflictError)
are not caught here — they propagate to the global handlers registered
in app.core.error_handlers, which map them to the appropriate HTTP
status code.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_event_publisher
from app.core.session import get_db
from app.events.base import EventPublisher
from app.repositories.alert import AlertRepository
from app.schemas.alert import AlertRead
from app.services.alert import AlertService

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[AlertRead])
async def list_alerts(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    event_publisher: EventPublisher = Depends(get_event_publisher),
) -> list[AlertRead]:
    """List alerts, defaulting to only currently active ones.

    Args:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return.
        active_only: If True (the default), only alerts with an ACTIVE
            status are returned. Set to False to include resolved
            alerts as well, for historical review.
        db: Injected async database session.
        event_publisher: Injected domain event publisher.

    Returns:
        list[AlertRead]: The matching alerts.
    """
    if active_only:
        service = AlertService(db, event_publisher)
        alerts = await service.list_active_alerts(skip=skip, limit=limit)
    else:
        repository = AlertRepository(db)
        alerts = await repository.list_all(skip=skip, limit=limit)
    return [AlertRead.model_validate(alert) for alert in alerts]


@router.get("/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlertRead:
    """Fetch a single alert by id.

    Args:
        alert_id: The alert's UUID.
        db: Injected async database session.

    Returns:
        AlertRead: The matching alert.

    Raises:
        NotFoundError: If no alert exists with the given id (translated
            to a 404 response by the global handler).
    """
    repository = AlertRepository(db)
    alert = await repository.get_by_id_or_raise(alert_id)
    return AlertRead.model_validate(alert)


@router.post("/{alert_id}/resolve", response_model=AlertRead)
async def resolve_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_publisher: EventPublisher = Depends(get_event_publisher),
) -> AlertRead:
    """Manually resolve an active alert.

    Args:
        alert_id: The alert's UUID.
        db: Injected async database session.
        event_publisher: Injected domain event publisher.

    Returns:
        AlertRead: The resolved alert.

    Raises:
        NotFoundError: If no alert exists with the given id (translated
            to a 404 response by the global handler).
        ConflictError: If the alert is already resolved (translated to
            a 409 response).
    """
    service = AlertService(db, event_publisher)
    alert = await service.resolve_alert(alert_id)
    return AlertRead.model_validate(alert)

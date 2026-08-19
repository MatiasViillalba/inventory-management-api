"""Endpoints for inventory alerts.

Alerts are created and escalated internally by AlertService in
reaction to stock-level changes (see AlertService.evaluate_stock_level,
invoked from the inventory write side) — clients never create an alert
directly. This module exposes read routes over the alert history and
the one client-triggered mutation: manually resolving an active alert.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.session import get_db
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
) -> list[AlertRead]:
    """List alerts, defaulting to only currently active ones.

    Args:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return.
        active_only: If True (the default), only alerts with an ACTIVE
            status are returned. Set to False to include resolved
            alerts as well, for historical review.
        db: Injected async database session.

    Returns:
        list[AlertRead]: The matching alerts.
    """
    if active_only:
        service = AlertService(db)
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
        HTTPException: 404 if no alert exists with the given id.
    """
    repository = AlertRepository(db)
    try:
        alert = await repository.get_by_id_or_raise(alert_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AlertRead.model_validate(alert)


@router.post("/{alert_id}/resolve", response_model=AlertRead)
async def resolve_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlertRead:
    """Manually resolve an active alert.

    Args:
        alert_id: The alert's UUID.
        db: Injected async database session.

    Returns:
        AlertRead: The resolved alert.

    Raises:
        HTTPException: 404 if no alert exists with the given id, or 409
            if the alert is already resolved.
    """
    service = AlertService(db)
    try:
        alert = await service.resolve_alert(alert_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return AlertRead.model_validate(alert)

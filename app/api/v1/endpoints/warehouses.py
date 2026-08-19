"""Read endpoints for warehouse resources.

Exposes list and detail routes backed by WarehouseService. Write
operations (create, update, deactivate) are added in a later commit to
keep this one focused on the query side of the resource.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.session import get_db
from app.schemas.warehouse import WarehouseRead
from app.services.warehouse import WarehouseService

router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


@router.get("", response_model=list[WarehouseRead])
async def list_warehouses(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[WarehouseRead]:
    """List warehouses with pagination and an optional active-only filter.

    Args:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return.
        active_only: If True, only warehouses with is_active=True are
            returned.
        db: Injected async database session.

    Returns:
        list[WarehouseRead]: The matching warehouses.
    """
    service = WarehouseService(db)
    warehouses = await service.list_warehouses(
        skip=skip, limit=limit, active_only=active_only
    )
    return [WarehouseRead.model_validate(warehouse) for warehouse in warehouses]


@router.get("/{warehouse_id}", response_model=WarehouseRead)
async def get_warehouse(
    warehouse_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WarehouseRead:
    """Fetch a single warehouse by id.

    Args:
        warehouse_id: The warehouse's UUID.
        db: Injected async database session.

    Returns:
        WarehouseRead: The matching warehouse.

    Raises:
        HTTPException: 404 if no warehouse exists with the given id.
    """
    service = WarehouseService(db)
    try:
        warehouse = await service.get_warehouse(warehouse_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return WarehouseRead.model_validate(warehouse)

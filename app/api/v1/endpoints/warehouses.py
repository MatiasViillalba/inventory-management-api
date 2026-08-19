"""CRUD endpoints for warehouse resources.

Exposes list, detail, create, update, and deactivate routes backed by
WarehouseService. Warehouses are never hard-deleted: the DELETE route
performs a soft delete (is_active=False) so historical inventory and
movement records remain valid and auditable.

Domain exceptions raised by the service (NotFoundError, ConflictError)
are not caught here — they propagate to the global handlers registered
in app.core.error_handlers, which map them to the appropriate HTTP
status code.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db
from app.schemas.warehouse import WarehouseCreate, WarehouseRead, WarehouseUpdate
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
        NotFoundError: If no warehouse exists with the given id
            (translated to a 404 response by the global handler).
    """
    service = WarehouseService(db)
    warehouse = await service.get_warehouse(warehouse_id)
    return WarehouseRead.model_validate(warehouse)


@router.post("", response_model=WarehouseRead, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    data: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
) -> WarehouseRead:
    """Create a new warehouse.

    Args:
        data: Validated warehouse creation payload.
        db: Injected async database session.

    Returns:
        WarehouseRead: The newly created warehouse.

    Raises:
        ConflictError: If a warehouse with the same code already exists
            (translated to a 409 response by the global handler).
    """
    service = WarehouseService(db)
    warehouse = await service.create_warehouse(data)
    return WarehouseRead.model_validate(warehouse)


@router.put("/{warehouse_id}", response_model=WarehouseRead)
async def update_warehouse(
    warehouse_id: uuid.UUID,
    data: WarehouseUpdate,
    db: AsyncSession = Depends(get_db),
) -> WarehouseRead:
    """Partially update an existing warehouse.

    Args:
        warehouse_id: The warehouse's UUID.
        data: Fields to update; unset fields are left unchanged.
        db: Injected async database session.

    Returns:
        WarehouseRead: The updated warehouse.

    Raises:
        NotFoundError: If no warehouse exists with the given id
            (translated to a 404 response by the global handler).
        ConflictError: If the update would set a code already used by
            another warehouse (translated to a 409 response).
    """
    service = WarehouseService(db)
    warehouse = await service.update_warehouse(warehouse_id, data)
    return WarehouseRead.model_validate(warehouse)


@router.delete("/{warehouse_id}", response_model=WarehouseRead)
async def deactivate_warehouse(
    warehouse_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WarehouseRead:
    """Soft-delete a warehouse by marking it inactive.

    Args:
        warehouse_id: The warehouse's UUID.
        db: Injected async database session.

    Returns:
        WarehouseRead: The deactivated warehouse.

    Raises:
        NotFoundError: If no warehouse exists with the given id
            (translated to a 404 response by the global handler).
    """
    service = WarehouseService(db)
    warehouse = await service.deactivate_warehouse(warehouse_id)
    return WarehouseRead.model_validate(warehouse)

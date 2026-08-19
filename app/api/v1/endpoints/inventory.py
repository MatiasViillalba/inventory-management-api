"""Endpoints for inventory (stock level) queries and stock movements.

Combines both halves of the CQRS split for the Inventory aggregate:
GET routes are backed by InventoryQueryService (read-only), and the
POST route is backed by InventoryCommandService, which applies stock
changes under row-level locking and appends an immutable Movement
audit record. Inventory records are never created or mutated directly
— every stock change goes through a Movement.

Domain exceptions raised by the services (NotFoundError,
InsufficientStockError) are not caught here — they propagate to the
global handlers registered in app.core.error_handlers, which map them
to the appropriate HTTP status code.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db
from app.schemas.inventory import InventoryRead
from app.schemas.movement import MovementCreate, MovementRead
from app.services.inventory_command import InventoryCommandService
from app.services.inventory_query import InventoryQueryService

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("", response_model=list[InventoryRead])
async def list_inventory(
    skip: int = 0,
    limit: int = 100,
    warehouse_id: uuid.UUID | None = None,
    low_stock_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[InventoryRead]:
    """List inventory records, optionally filtered by warehouse or stock state.

    Args:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return.
        warehouse_id: If provided, restrict results to this warehouse.
            Takes precedence over low_stock_only.
        low_stock_only: If True, only records at or below their
            low-stock threshold are returned. Ignored when warehouse_id
            is provided.
        db: Injected async database session.

    Returns:
        list[InventoryRead]: The matching inventory records.
    """
    service = InventoryQueryService(db)
    if warehouse_id is not None:
        records = await service.list_warehouse_stock(warehouse_id, skip=skip, limit=limit)
    elif low_stock_only:
        records = await service.list_low_stock(skip=skip, limit=limit)
    else:
        records = await service.list_all_stock(skip=skip, limit=limit)
    return [InventoryRead.model_validate(record) for record in records]


@router.get("/{product_id}/{warehouse_id}", response_model=InventoryRead)
async def get_stock_level(
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InventoryRead:
    """Fetch the current stock level for a product in a warehouse.

    Args:
        product_id: The product's UUID.
        warehouse_id: The warehouse's UUID.
        db: Injected async database session.

    Returns:
        InventoryRead: The matching inventory record.

    Raises:
        NotFoundError: If the product has no stock record in that
            warehouse yet (translated to a 404 response by the global
            handler).
    """
    service = InventoryQueryService(db)
    record = await service.get_stock_level(product_id, warehouse_id)
    return InventoryRead.model_validate(record)


@router.post("", response_model=MovementRead, status_code=status.HTTP_201_CREATED)
async def record_movement(
    data: MovementCreate,
    db: AsyncSession = Depends(get_db),
) -> MovementRead:
    """Apply a stock movement (add, remove, or transfer) and record it.

    Which warehouse fields are required depends on movement_type — see
    MovementCreate for the exact rules. The affected inventory row(s)
    are locked for the duration of the operation, and an immutable
    Movement record is appended as the audit trail.

    Args:
        data: Validated movement payload (IN, OUT, or TRANSFER).
        db: Injected async database session.

    Returns:
        MovementRead: The newly created movement record.

    Raises:
        NotFoundError: If the product or a referenced warehouse does
            not exist (translated to a 404 response by the global
            handler).
        InsufficientStockError: If an OUT or TRANSFER movement would
            reduce a stock level below zero (translated to a 409
            response).
    """
    service = InventoryCommandService(db)
    movement = await service.record_movement(data)
    return MovementRead.model_validate(movement)

"""Read endpoints for inventory (stock level) queries.

Backed by InventoryQueryService, the read half of the CQRS split for
the Inventory aggregate. Inventory records are never created or
mutated directly through these routes — stock changes happen via the
Movement-driven write side (POST /inventory), added in a later commit.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.session import get_db
from app.schemas.inventory import InventoryRead
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
        HTTPException: 404 if the product has no stock record in that
            warehouse yet.
    """
    service = InventoryQueryService(db)
    try:
        record = await service.get_stock_level(product_id, warehouse_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return InventoryRead.model_validate(record)

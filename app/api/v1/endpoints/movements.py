"""Read endpoints for the movement audit trail.

Movement rows are an immutable audit trail written exclusively by
InventoryCommandService (see POST /inventory) — this module exposes no
write routes. Queries are simple pass-throughs with no business logic
beyond filtering and pagination, so they go straight through
MovementRepository rather than a dedicated service layer.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.session import get_db
from app.repositories.movement import MovementRepository
from app.schemas.movement import MovementRead

router = APIRouter(prefix="/movements", tags=["Movements"])


@router.get("", response_model=list[MovementRead])
async def list_movements(
    skip: int = 0,
    limit: int = 100,
    product_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MovementRead]:
    """List movements, optionally filtered by product or warehouse.

    Args:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return.
        product_id: If provided, restrict results to movements for this
            product. Takes precedence over warehouse_id.
        warehouse_id: If provided, restrict results to movements where
            this warehouse was the source or destination. Ignored when
            product_id is provided.
        db: Injected async database session.

    Returns:
        list[MovementRead]: The matching movements, most recent first.
    """
    repository = MovementRepository(db)
    if product_id is not None:
        movements = await repository.list_by_product(product_id, skip=skip, limit=limit)
    elif warehouse_id is not None:
        movements = await repository.list_by_warehouse(warehouse_id, skip=skip, limit=limit)
    else:
        movements = await repository.list_all(skip=skip, limit=limit)
    return [MovementRead.model_validate(movement) for movement in movements]


@router.get("/{movement_id}", response_model=MovementRead)
async def get_movement(
    movement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MovementRead:
    """Fetch a single movement by id.

    Args:
        movement_id: The movement's UUID.
        db: Injected async database session.

    Returns:
        MovementRead: The matching movement.

    Raises:
        HTTPException: 404 if no movement exists with the given id.
    """
    repository = MovementRepository(db)
    try:
        movement = await repository.get_by_id_or_raise(movement_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return MovementRead.model_validate(movement)

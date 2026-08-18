"""Repository for Movement data access.

Extends BaseRepository with read-only query methods specific to the
Movement aggregate. Movement rows are an immutable audit trail, so this
repository intentionally exposes no update logic beyond the generic
create/delete inherited from BaseRepository.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movement import Movement
from app.repositories.base import BaseRepository


class MovementRepository(BaseRepository[Movement]):
    """Data-access layer for Movement entities.

    Attributes:
        session: The active async database session, inherited from
            BaseRepository.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository bound to the Movement model.

        Args:
            session: An active AsyncSession injected by the caller.
        """
        super().__init__(Movement, session)

    async def list_by_product(
        self, product_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Movement]:
        """List the audit history of movements for a single product.

        Args:
            product_id: The product's UUID.
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of movements for the product, most recent first.
        """
        statement = (
            select(Movement)
            .where(Movement.product_id == product_id)
            .order_by(Movement.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_by_warehouse(
        self, warehouse_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Movement]:
        """List movements where a warehouse was the source or destination.

        Args:
            warehouse_id: The warehouse's UUID.
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of movements involving the warehouse, most recent first.
        """
        statement = (
            select(Movement)
            .where(
                (Movement.source_warehouse_id == warehouse_id)
                | (Movement.destination_warehouse_id == warehouse_id)
            )
            .order_by(Movement.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

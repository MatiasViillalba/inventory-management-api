"""Repository for Inventory data access.

Extends BaseRepository with query methods specific to the Inventory
aggregate: lookups by the (product, warehouse) composite key, a
row-locking variant used by write operations to prevent race
conditions under concurrent stock updates, and low-stock detection
used by the alerting subsystem.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Inventory
from app.repositories.base import BaseRepository


class InventoryRepository(BaseRepository[Inventory]):
    """Data-access layer for Inventory entities.

    Attributes:
        session: The active async database session, inherited from
            BaseRepository.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository bound to the Inventory model.

        Args:
            session: An active AsyncSession injected by the caller.
        """
        super().__init__(Inventory, session)

    async def get_by_product_and_warehouse(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        """Fetch the inventory record for a product in a warehouse.

        Args:
            product_id: The product's UUID.
            warehouse_id: The warehouse's UUID.

        Returns:
            The matching Inventory, or None if the pair has no stock
            record yet.
        """
        statement = select(Inventory).where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_product_and_warehouse_for_update(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        """Fetch an inventory record with a row-level write lock.

        Issues SELECT ... FOR UPDATE so concurrent stock-mutating
        transactions on the same (product, warehouse) pair are
        serialized at the database level, preventing lost updates when
        multiple movements race to modify the same quantity. Intended
        for use exclusively by write-side service operations, inside an
        existing transaction.

        Args:
            product_id: The product's UUID.
            warehouse_id: The warehouse's UUID.

        Returns:
            The matching Inventory locked for update, or None if the
            pair has no stock record yet.
        """
        statement = (
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
            )
            .with_for_update()
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_warehouse(
        self, warehouse_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Inventory]:
        """List all inventory records held by a specific warehouse.

        Args:
            warehouse_id: The warehouse's UUID.
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of inventory records for the given warehouse.
        """
        statement = (
            select(Inventory)
            .where(Inventory.warehouse_id == warehouse_id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_low_stock(self, skip: int = 0, limit: int = 100) -> list[Inventory]:
        """List inventory records at or below their low-stock threshold.

        Records without a per-record threshold configured are excluded;
        the global default threshold is applied at the service layer.

        Args:
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of inventory records currently in a low-stock state.
        """
        statement = (
            select(Inventory)
            .where(
                Inventory.low_stock_threshold.is_not(None),
                Inventory.quantity <= Inventory.low_stock_threshold,
            )
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

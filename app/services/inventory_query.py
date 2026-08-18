"""Read-side (CQRS query) business logic for inventory.

InventoryQueryService is the query half of the CQRS split for the
Inventory aggregate: it only reads stock data and never mutates it, so
it requires no row locking and no transaction commits. The write half,
which applies stock changes under a row lock, lives in
InventoryCommandService (app/services/inventory_command.py).

Keeping queries and commands in separate classes makes the read/write
boundary explicit in the code, not just in documentation, and lets the
query side evolve (e.g. adding caching) without touching write-side
concurrency guarantees.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Inventory
from app.repositories.inventory import InventoryRepository
from app.core.exceptions import NotFoundError


class InventoryQueryService:
    """Read-only queries over current inventory levels.

    Attributes:
        repository: The data-access layer for Inventory entities.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
        """
        self.repository = InventoryRepository(session)

    async def get_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory:
        """Fetch the current stock level for a product in a warehouse.

        Args:
            product_id: The product's UUID.
            warehouse_id: The warehouse's UUID.

        Returns:
            The matching Inventory record.

        Raises:
            NotFoundError: If the product has no stock record in that
                warehouse yet (i.e. it has never been received there).
        """
        inventory = await self.repository.get_by_product_and_warehouse(
            product_id, warehouse_id
        )
        if inventory is None:
            raise NotFoundError(
                f"No inventory record for product '{product_id}' in "
                f"warehouse '{warehouse_id}'."
            )
        return inventory

    async def list_warehouse_stock(
        self, warehouse_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Inventory]:
        """List all stock records held by a specific warehouse.

        Args:
            warehouse_id: The warehouse's UUID.
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.

        Returns:
            A list of inventory records for the given warehouse.
        """
        return await self.repository.list_by_warehouse(warehouse_id, skip=skip, limit=limit)

    async def list_low_stock(self, skip: int = 0, limit: int = 100) -> list[Inventory]:
        """List inventory records at or below their low-stock threshold.

        Args:
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.

        Returns:
            A list of inventory records currently in a low-stock state.
        """
        return await self.repository.list_low_stock(skip=skip, limit=limit)

    async def list_all_stock(self, skip: int = 0, limit: int = 100) -> list[Inventory]:
        """List all inventory records across every warehouse.

        Args:
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.

        Returns:
            A list of inventory records.
        """
        return await self.repository.list_all(skip=skip, limit=limit)

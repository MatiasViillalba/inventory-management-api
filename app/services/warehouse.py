"""Business logic for warehouse management.

WarehouseService owns the transaction boundary for warehouse
operations: it validates business rules (e.g. code uniqueness),
delegates persistence to WarehouseRepository, and commits or rolls
back the unit of work. API endpoints depend on this service rather
than talking to the repository directly.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.warehouse import Warehouse
from app.repositories.warehouse import WarehouseRepository
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate


class WarehouseService:
    """Coordinates warehouse business rules and persistence.

    Attributes:
        session: The active async database session.
        repository: The data-access layer for Warehouse entities.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
        """
        self.session = session
        self.repository = WarehouseRepository(session)

    async def create_warehouse(self, data: WarehouseCreate) -> Warehouse:
        """Create a new warehouse after validating code uniqueness.

        Args:
            data: Validated warehouse creation payload.

        Returns:
            The newly created Warehouse.

        Raises:
            ConflictError: If a warehouse with the same code already exists.
        """
        existing = await self.repository.get_by_code(data.code)
        if existing is not None:
            raise ConflictError(f"Warehouse with code '{data.code}' already exists.")

        warehouse = Warehouse(**data.model_dump())
        warehouse = await self.repository.create(warehouse)
        await self.session.commit()
        return warehouse

    async def get_warehouse(self, warehouse_id: uuid.UUID) -> Warehouse:
        """Fetch a single warehouse by id.

        Args:
            warehouse_id: The warehouse's UUID.

        Returns:
            The matching Warehouse.

        Raises:
            NotFoundError: If no warehouse exists with the given id.
        """
        return await self.repository.get_by_id_or_raise(warehouse_id)

    async def list_warehouses(
        self, skip: int = 0, limit: int = 100, active_only: bool = False
    ) -> list[Warehouse]:
        """List warehouses, optionally restricted to active ones.

        Args:
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.
            active_only: If True, only warehouses with is_active=True are
                returned.

        Returns:
            A list of warehouses.
        """
        if active_only:
            return await self.repository.list_active(skip=skip, limit=limit)
        return await self.repository.list_all(skip=skip, limit=limit)

    async def update_warehouse(
        self, warehouse_id: uuid.UUID, data: WarehouseUpdate
    ) -> Warehouse:
        """Partially update an existing warehouse.

        Args:
            warehouse_id: The warehouse's UUID.
            data: Fields to update; unset fields are left unchanged.

        Returns:
            The updated Warehouse.

        Raises:
            NotFoundError: If no warehouse exists with the given id.
            ConflictError: If the update would set a code that is already
                used by a different warehouse.
        """
        warehouse = await self.repository.get_by_id_or_raise(warehouse_id)

        updates = data.model_dump(exclude_unset=True)
        new_code = updates.get("code")
        if new_code is not None and new_code != warehouse.code:
            existing = await self.repository.get_by_code(new_code)
            if existing is not None:
                raise ConflictError(f"Warehouse with code '{new_code}' already exists.")

        for field, value in updates.items():
            setattr(warehouse, field, value)

        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

    async def deactivate_warehouse(self, warehouse_id: uuid.UUID) -> Warehouse:
        """Soft-delete a warehouse by marking it inactive.

        Warehouses are never hard-deleted so that historical inventory
        and movement records remain valid and auditable.

        Args:
            warehouse_id: The warehouse's UUID.

        Returns:
            The deactivated Warehouse.

        Raises:
            NotFoundError: If no warehouse exists with the given id.
        """
        warehouse = await self.repository.get_by_id_or_raise(warehouse_id)
        warehouse.is_active = False
        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

"""Repository for Warehouse data access.

Extends BaseRepository with query methods specific to the Warehouse
aggregate, such as lookups by its unique natural key (code) and
filtering by active status.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.warehouse import Warehouse
from app.repositories.base import BaseRepository


class WarehouseRepository(BaseRepository[Warehouse]):
    """Data-access layer for Warehouse entities.

    Attributes:
        session: The active async database session, inherited from
            BaseRepository.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository bound to the Warehouse model.

        Args:
            session: An active AsyncSession injected by the caller.
        """
        super().__init__(Warehouse, session)

    async def get_by_code(self, code: str) -> Warehouse | None:
        """Fetch a warehouse by its unique short code.

        Args:
            code: The unique warehouse code (e.g. "WH-NYC-01").

        Returns:
            The matching Warehouse, or None if no warehouse has that code.
        """
        statement = select(Warehouse).where(Warehouse.code == code)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Warehouse]:
        """List warehouses that currently participate in operations.

        Args:
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of active warehouses, ordered by database default order.
        """
        statement = (
            select(Warehouse)
            .where(Warehouse.is_active.is_(True))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

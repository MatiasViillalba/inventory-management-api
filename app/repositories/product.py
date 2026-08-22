"""Repository for Product data access.

Extends BaseRepository with query methods specific to the Product
aggregate, such as lookups by its unique natural key (SKU), filtering
by active status, and case-insensitive name search for catalog
browsing.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    """Data-access layer for Product entities.

    Attributes:
        session: The active async database session, inherited from
            BaseRepository.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository bound to the Product model.

        Args:
            session: An active AsyncSession injected by the caller.
        """
        super().__init__(Product, session)

    async def get_by_sku(self, sku: str) -> Product | None:
        """Fetch a product by its unique stock-keeping unit.

        Args:
            sku: The unique SKU identifying the product.

        Returns:
            The matching Product, or None if no product has that SKU.
        """
        statement = select(Product).where(Product.sku == sku)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Product]:
        """List products that are currently sellable/stockable.

        Args:
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of active products, ordered by database default order.
        """
        statement = (
            select(Product).where(Product.is_active.is_(True)).offset(skip).limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def search_by_name(
        self, query: str, skip: int = 0, limit: int = 100
    ) -> list[Product]:
        """Search active products whose name contains the given query.

        Args:
            query: Case-insensitive substring to match against product names.
            skip: Number of rows to skip from the start of the result set.
            limit: Maximum number of rows to return.

        Returns:
            A list of matching products, ordered by database default order.
        """
        statement = (
            select(Product)
            .where(Product.name.ilike(f"%{query}%"))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

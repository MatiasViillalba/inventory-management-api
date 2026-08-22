"""Business logic for product catalog management.

ProductService owns the transaction boundary for product operations:
it validates business rules (e.g. SKU uniqueness), delegates
persistence to ProductRepository, and commits or rolls back the unit
of work. API endpoints depend on this service rather than talking to
the repository directly.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.product import Product
from app.repositories.product import ProductRepository
from app.schemas.product import ProductCreate, ProductUpdate


class ProductService:
    """Coordinates product business rules and persistence.

    Attributes:
        session: The active async database session.
        repository: The data-access layer for Product entities.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
        """
        self.session = session
        self.repository = ProductRepository(session)

    async def create_product(self, data: ProductCreate) -> Product:
        """Create a new product after validating SKU uniqueness.

        Args:
            data: Validated product creation payload.

        Returns:
            The newly created Product.

        Raises:
            ConflictError: If a product with the same SKU already exists.
        """
        existing = await self.repository.get_by_sku(data.sku)
        if existing is not None:
            raise ConflictError(f"Product with SKU '{data.sku}' already exists.")

        product = Product(**data.model_dump())
        product = await self.repository.create(product)
        await self.session.commit()
        return product

    async def get_product(self, product_id: uuid.UUID) -> Product:
        """Fetch a single product by id.

        Args:
            product_id: The product's UUID.

        Returns:
            The matching Product.

        Raises:
            NotFoundError: If no product exists with the given id.
        """
        return await self.repository.get_by_id_or_raise(product_id)

    async def list_products(
        self, skip: int = 0, limit: int = 100, active_only: bool = False
    ) -> list[Product]:
        """List products, optionally restricted to active ones.

        Args:
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.
            active_only: If True, only products with is_active=True are
                returned.

        Returns:
            A list of products.
        """
        if active_only:
            return await self.repository.list_active(skip=skip, limit=limit)
        return await self.repository.list_all(skip=skip, limit=limit)

    async def search_products(
        self, query: str, skip: int = 0, limit: int = 100
    ) -> list[Product]:
        """Search products by a case-insensitive name substring.

        Args:
            query: Substring to match against product names.
            skip: Number of records to skip from the start of the result set.
            limit: Maximum number of records to return.

        Returns:
            A list of matching products.
        """
        return await self.repository.search_by_name(query, skip=skip, limit=limit)

    async def update_product(
        self, product_id: uuid.UUID, data: ProductUpdate
    ) -> Product:
        """Partially update an existing product.

        Args:
            product_id: The product's UUID.
            data: Fields to update; unset fields are left unchanged.

        Returns:
            The updated Product.

        Raises:
            NotFoundError: If no product exists with the given id.
            ConflictError: If the update would set a SKU that is already
                used by a different product.
        """
        product = await self.repository.get_by_id_or_raise(product_id)

        updates = data.model_dump(exclude_unset=True)
        new_sku = updates.get("sku")
        if new_sku is not None and new_sku != product.sku:
            existing = await self.repository.get_by_sku(new_sku)
            if existing is not None:
                raise ConflictError(f"Product with SKU '{new_sku}' already exists.")

        for field, value in updates.items():
            setattr(product, field, value)

        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def deactivate_product(self, product_id: uuid.UUID) -> Product:
        """Soft-delete a product by marking it inactive.

        Products are never hard-deleted so that historical inventory
        and movement records remain valid and auditable.

        Args:
            product_id: The product's UUID.

        Returns:
            The deactivated Product.

        Raises:
            NotFoundError: If no product exists with the given id.
        """
        product = await self.repository.get_by_id_or_raise(product_id)
        product.is_active = False
        await self.session.commit()
        await self.session.refresh(product)
        return product

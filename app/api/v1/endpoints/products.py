"""CRUD endpoints for product resources.

Exposes list, search, detail, create, update, and deactivate routes
backed by ProductService. Products are never hard-deleted: the DELETE
route performs a soft delete (is_active=False) so historical inventory
and movement records remain valid and auditable.

Domain exceptions raised by the service (NotFoundError, ConflictError)
are not caught here — they propagate to the global handlers registered
in app.core.error_handlers, which map them to the appropriate HTTP
status code.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.responses import CONFLICT, NOT_FOUND
from app.core.session import get_db
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.product import ProductService

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=list[ProductRead])
async def list_products(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ProductRead]:
    """List products with pagination, or search by name substring.

    Args:
        skip: Number of records to skip from the start of the result set.
        limit: Maximum number of records to return.
        active_only: If True, only products with is_active=True are
            returned. Ignored when search is provided.
        search: Optional case-insensitive substring to match against
            product names. When provided, takes precedence over
            active_only.
        db: Injected async database session.

    Returns:
        list[ProductRead]: The matching products.
    """
    service = ProductService(db)
    if search:
        products = await service.search_products(search, skip=skip, limit=limit)
    else:
        products = await service.list_products(
            skip=skip, limit=limit, active_only=active_only
        )
    return [ProductRead.model_validate(product) for product in products]


@router.get("/{product_id}", response_model=ProductRead, responses=NOT_FOUND)
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    """Fetch a single product by id.

    Args:
        product_id: The product's UUID.
        db: Injected async database session.

    Returns:
        ProductRead: The matching product.

    Raises:
        NotFoundError: If no product exists with the given id
            (translated to a 404 response by the global handler).
    """
    service = ProductService(db)
    product = await service.get_product(product_id)
    return ProductRead.model_validate(product)


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    responses=CONFLICT,
)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    """Create a new product.

    Args:
        data: Validated product creation payload.
        db: Injected async database session.

    Returns:
        ProductRead: The newly created product.

    Raises:
        ConflictError: If a product with the same SKU already exists
            (translated to a 409 response by the global handler).
    """
    service = ProductService(db)
    product = await service.create_product(data)
    return ProductRead.model_validate(product)


@router.put(
    "/{product_id}",
    response_model=ProductRead,
    responses={**NOT_FOUND, **CONFLICT},
)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    """Partially update an existing product.

    Args:
        product_id: The product's UUID.
        data: Fields to update; unset fields are left unchanged.
        db: Injected async database session.

    Returns:
        ProductRead: The updated product.

    Raises:
        NotFoundError: If no product exists with the given id
            (translated to a 404 response by the global handler).
        ConflictError: If the update would set a SKU already used by
            another product (translated to a 409 response).
    """
    service = ProductService(db)
    product = await service.update_product(product_id, data)
    return ProductRead.model_validate(product)


@router.delete("/{product_id}", response_model=ProductRead, responses=NOT_FOUND)
async def deactivate_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    """Soft-delete a product by marking it inactive.

    Args:
        product_id: The product's UUID.
        db: Injected async database session.

    Returns:
        ProductRead: The deactivated product.

    Raises:
        NotFoundError: If no product exists with the given id
            (translated to a 404 response by the global handler).
    """
    service = ProductService(db)
    product = await service.deactivate_product(product_id)
    return ProductRead.model_validate(product)

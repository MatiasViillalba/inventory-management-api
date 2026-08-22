"""Unit tests for ORM models.

These models carry no business logic of their own — that lives in the
service layer — so what's worth verifying here is the persistence
contract each model declares: primary key/timestamp generation
(BaseModel), column defaults, and the unique/not-null constraints that
guard data integrity at the database level. Each test therefore
round-trips through `db_session` rather than only constructing Python
objects in memory, since defaults like `server_default=func.now()` and
unique constraints are enforced by Postgres, not by SQLAlchemy itself.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.inventory import Inventory
from app.models.movement import Movement, MovementType
from app.models.product import Product
from app.models.user import User
from app.models.warehouse import Warehouse


class TestBaseModel:
    """Tests for the shared id/timestamp behavior in BaseModel."""

    async def test_generates_uuid_primary_key_on_insert(self, db_session: AsyncSession) -> None:
        warehouse = Warehouse(name="Depot", code="DEP-1")
        db_session.add(warehouse)
        await db_session.commit()
        await db_session.refresh(warehouse)

        assert isinstance(warehouse.id, uuid.UUID)

    async def test_sets_created_and_updated_at_on_insert(self, db_session: AsyncSession) -> None:
        warehouse = Warehouse(name="Depot", code="DEP-2")
        db_session.add(warehouse)
        await db_session.commit()
        await db_session.refresh(warehouse)

        assert warehouse.created_at is not None
        assert warehouse.updated_at is not None

    async def test_refreshes_updated_at_on_update(self, db_session: AsyncSession) -> None:
        warehouse = Warehouse(name="Depot", code="DEP-3")
        db_session.add(warehouse)
        await db_session.commit()
        await db_session.refresh(warehouse)
        original_updated_at = warehouse.updated_at

        warehouse.name = "Renamed Depot"
        await db_session.commit()
        await db_session.refresh(warehouse)

        assert warehouse.updated_at >= original_updated_at


class TestWarehouseModel:
    """Tests for the Warehouse model's defaults and constraints."""

    async def test_is_active_defaults_to_true(self, db_session: AsyncSession) -> None:
        warehouse = Warehouse(name="Depot", code="DEP-10")
        db_session.add(warehouse)
        await db_session.commit()
        await db_session.refresh(warehouse)

        assert warehouse.is_active is True

    async def test_code_must_be_unique(self, db_session: AsyncSession) -> None:
        db_session.add(Warehouse(name="Depot A", code="DUP"))
        await db_session.commit()

        db_session.add(Warehouse(name="Depot B", code="DUP"))
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestProductModel:
    """Tests for the Product model's defaults and constraints."""

    async def test_is_active_defaults_to_true(self, db_session: AsyncSession) -> None:
        product = Product(sku="SKU-100", name="Widget", price=Decimal("9.99"))
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        assert product.is_active is True

    async def test_sku_must_be_unique(self, db_session: AsyncSession) -> None:
        db_session.add(Product(sku="SKU-DUP", name="Widget A", price=Decimal("1.00")))
        await db_session.commit()

        db_session.add(Product(sku="SKU-DUP", name="Widget B", price=Decimal("2.00")))
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_price_persists_as_decimal(self, db_session: AsyncSession) -> None:
        product = Product(sku="SKU-101", name="Widget", price=Decimal("199.95"))
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        assert product.price == Decimal("199.95")


class TestInventoryModel:
    """Tests for the Inventory model's defaults and constraints."""

    async def test_quantity_defaults_to_zero(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        inventory = Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id)
        db_session.add(inventory)
        await db_session.commit()
        await db_session.refresh(inventory)

        assert inventory.quantity == 0

    async def test_product_and_warehouse_pair_must_be_unique(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        db_session.add(Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=5))
        await db_session.commit()

        db_session.add(Inventory(product_id=test_product.id, warehouse_id=test_warehouse.id, quantity=10))
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestMovementModel:
    """Tests for the Movement model's enum and nullability behavior."""

    async def test_movement_type_round_trips_through_enum(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        movement = Movement(
            product_id=test_product.id,
            movement_type=MovementType.IN,
            quantity=25,
            destination_warehouse_id=test_warehouse.id,
        )
        db_session.add(movement)
        await db_session.commit()
        await db_session.refresh(movement)

        assert movement.movement_type is MovementType.IN

    async def test_source_warehouse_is_nullable_for_inbound_movement(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        movement = Movement(
            product_id=test_product.id,
            movement_type=MovementType.IN,
            quantity=25,
            destination_warehouse_id=test_warehouse.id,
        )
        db_session.add(movement)
        await db_session.commit()
        await db_session.refresh(movement)

        assert movement.source_warehouse_id is None


class TestAlertModel:
    """Tests for the Alert model's defaults and enum behavior."""

    async def test_status_defaults_to_active(
        self, db_session: AsyncSession, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        alert = Alert(
            product_id=test_product.id,
            warehouse_id=test_warehouse.id,
            alert_type=AlertType.LOW_STOCK,
            threshold=10,
            quantity_at_trigger=3,
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        assert alert.status is AlertStatus.ACTIVE
        assert alert.resolved_at is None


class TestUserModel:
    """Tests for the User model's defaults and constraints."""

    async def test_defaults_active_non_superuser(self, db_session: AsyncSession) -> None:
        user = User(email="new.user@example.com", hashed_password="hashed", full_name="New User")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.is_active is True
        assert user.is_superuser is False

    async def test_email_must_be_unique(self, db_session: AsyncSession) -> None:
        db_session.add(User(email="dup@example.com", hashed_password="hashed", full_name="First"))
        await db_session.commit()

        db_session.add(User(email="dup@example.com", hashed_password="hashed", full_name="Second"))
        with pytest.raises(IntegrityError):
            await db_session.commit()

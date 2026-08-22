"""Integration tests for the v1 REST API.

Unlike the unit tests in tests/unit/, these tests drive the application
through its actual HTTP surface (see the `client` fixture in
conftest.py) rather than calling services directly, so they verify the
whole request path: routing, Pydantic request/response validation, the
global exception handlers in app.core.error_handlers (domain exceptions
-> HTTP status codes), and JSON serialization.

None of these routes currently enforce authentication (see
app/api/deps.py's module docstring), so no Authorization header is
needed to exercise them.

Two external dependencies are handled specially:
- Celery's `.delay()` call for low-stock emails is monkeypatched out,
  same as in the service unit tests, so these tests never enqueue a
  real task on the broker.
- The report endpoints are wrapped in `cache_response` (a 60s Redis
  cache), so their tests flush the specific cache keys they use before
  each request — otherwise a stale cached report from an earlier test
  or run could mask the exact data this test just set up.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.core.config import get_settings
from app.models.product import Product
from app.models.warehouse import Warehouse

settings = get_settings()


class TestHealthEndpoint:
    """Tests for the health check route."""

    async def test_health_check_returns_ok(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}


class TestWarehousesEndpoints:
    """Tests for the /warehouses CRUD routes."""

    async def test_create_warehouse_returns_201(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/warehouses",
            json={"name": "API Depot", "code": "API-WH-1"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["code"] == "API-WH-1"
        assert body["is_active"] is True

    async def test_create_warehouse_invalid_payload_returns_422(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/warehouses", json={"name": "", "code": ""})

        assert response.status_code == 422

    async def test_create_warehouse_duplicate_code_returns_409(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/v1/warehouses", json={"name": "First", "code": "API-WH-DUP"})

        response = await client.post(
            "/api/v1/warehouses", json={"name": "Second", "code": "API-WH-DUP"}
        )

        assert response.status_code == 409

    async def test_get_warehouse_returns_404_when_missing(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/warehouses/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404

    async def test_list_warehouses_active_only_filter(self, client: AsyncClient) -> None:
        active = (
            await client.post(
                "/api/v1/warehouses", json={"name": "Active", "code": "API-WH-ACT"}
            )
        ).json()
        inactive = (
            await client.post(
                "/api/v1/warehouses", json={"name": "Inactive", "code": "API-WH-INACT"}
            )
        ).json()
        await client.delete(f"/api/v1/warehouses/{inactive['id']}")

        response = await client.get("/api/v1/warehouses", params={"active_only": True})

        codes = {warehouse["code"] for warehouse in response.json()}
        assert active["code"] in codes
        assert inactive["code"] not in codes

    async def test_update_warehouse_returns_updated_fields(self, client: AsyncClient) -> None:
        created = (
            await client.post(
                "/api/v1/warehouses", json={"name": "Old Name", "code": "API-WH-UPD"}
            )
        ).json()

        response = await client.put(
            f"/api/v1/warehouses/{created['id']}", json={"name": "New Name"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_deactivate_warehouse_soft_deletes(self, client: AsyncClient) -> None:
        created = (
            await client.post(
                "/api/v1/warehouses", json={"name": "To Deactivate", "code": "API-WH-DEL"}
            )
        ).json()

        response = await client.delete(f"/api/v1/warehouses/{created['id']}")

        assert response.status_code == 200
        assert response.json()["is_active"] is False


class TestProductsEndpoints:
    """Tests for the /products CRUD and search routes."""

    async def test_create_product_returns_201(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/products",
            json={"sku": "API-SKU-1", "name": "Widget", "price": "9.99"},
        )

        assert response.status_code == 201
        assert response.json()["sku"] == "API-SKU-1"

    async def test_create_product_invalid_price_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/products",
            json={"sku": "API-SKU-BAD", "name": "Widget", "price": "-1.00"},
        )

        assert response.status_code == 422

    async def test_create_product_duplicate_sku_returns_409(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/products",
            json={"sku": "API-SKU-DUP", "name": "Widget", "price": "1.00"},
        )

        response = await client.post(
            "/api/v1/products",
            json={"sku": "API-SKU-DUP", "name": "Other Widget", "price": "2.00"},
        )

        assert response.status_code == 409

    async def test_search_products_matches_name_substring(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/products",
            json={"sku": "API-SKU-SEARCH", "name": "Wireless Keyboard", "price": "49.99"},
        )

        response = await client.get("/api/v1/products", params={"search": "keyboard"})

        skus = {product["sku"] for product in response.json()}
        assert "API-SKU-SEARCH" in skus

    async def test_deactivate_product_soft_deletes(self, client: AsyncClient) -> None:
        created = (
            await client.post(
                "/api/v1/products",
                json={"sku": "API-SKU-DEL", "name": "Widget", "price": "1.00"},
            )
        ).json()

        response = await client.delete(f"/api/v1/products/{created['id']}")

        assert response.status_code == 200
        assert response.json()["is_active"] is False


class TestInventoryAndMovementsEndpoints:
    """Tests for the /inventory (stock) and /movements (audit trail) routes."""

    async def test_in_movement_returns_201_and_updates_stock(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )

        response = await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 30,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )

        assert response.status_code == 201
        assert response.json()["quantity"] == 30

        stock_response = await client.get(
            f"/api/v1/inventory/{test_product.id}/{test_warehouse.id}"
        )
        assert stock_response.status_code == 200
        assert stock_response.json()["quantity"] == 30

    async def test_movement_invalid_payload_returns_422(
        self, client: AsyncClient, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        response = await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 10,
                "destination_warehouse_id": str(test_warehouse.id),
                "source_warehouse_id": str(test_warehouse.id),
            },
        )

        assert response.status_code == 422

    async def test_out_movement_insufficient_stock_returns_409(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 5,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )

        response = await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "out",
                "quantity": 999,
                "source_warehouse_id": str(test_warehouse.id),
            },
        )

        assert response.status_code == 409

    async def test_get_stock_level_returns_404_when_missing(
        self, client: AsyncClient, test_product: Product, test_warehouse: Warehouse
    ) -> None:
        response = await client.get(
            f"/api/v1/inventory/{test_product.id}/{test_warehouse.id}"
        )

        assert response.status_code == 404

    async def test_list_movements_filtered_by_product(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 12,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )

        response = await client.get(
            "/api/v1/movements", params={"product_id": str(test_product.id)}
        )

        assert response.status_code == 200
        movements = response.json()
        assert len(movements) == 1
        assert movements[0]["quantity"] == 12


class TestAlertsEndpoints:
    """Tests for the /alerts read and resolve routes."""

    async def test_low_stock_movement_creates_alert_visible_via_api(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        # Global default low-stock threshold is 10; receiving fewer units
        # than that should raise an active LOW_STOCK alert.
        await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 4,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )

        response = await client.get("/api/v1/alerts")

        assert response.status_code == 200
        alerts = response.json()
        assert any(
            alert["product_id"] == str(test_product.id)
            and alert["warehouse_id"] == str(test_warehouse.id)
            and alert["alert_type"] == "low_stock"
            for alert in alerts
        )

    async def test_resolve_alert_returns_200_then_409_on_repeat(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 2,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )
        alerts = (await client.get("/api/v1/alerts")).json()
        alert_id = next(
            alert["id"]
            for alert in alerts
            if alert["product_id"] == str(test_product.id)
        )

        first_response = await client.post(f"/api/v1/alerts/{alert_id}/resolve")
        second_response = await client.post(f"/api/v1/alerts/{alert_id}/resolve")

        assert first_response.status_code == 200
        assert first_response.json()["status"] == "resolved"
        assert second_response.status_code == 409

    async def test_get_alert_returns_404_when_missing(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/alerts/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404


class TestReportsEndpoints:
    """Tests for the /reports aggregation routes."""

    @pytest.fixture(autouse=True)
    async def _clear_report_cache(self) -> None:
        """Flush the cached report payloads before each test.

        The report endpoints cache their response for 60 seconds under
        a key that doesn't vary by request (no query params), so a
        cached response from an earlier test would otherwise mask the
        data this test just set up.
        """
        async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
            await redis.delete("cache:reports:inventory-summary", "cache:reports:valuation")

    async def test_inventory_summary_reflects_current_stock(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 25,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )

        response = await client.get("/api/v1/reports/inventory-summary")

        assert response.status_code == 200
        by_warehouse = response.json()["by_warehouse"]
        summary = next(
            row for row in by_warehouse if row["warehouse_id"] == str(test_warehouse.id)
        )
        assert summary["total_quantity"] == 25

    async def test_valuation_report_computes_total_value(
        self,
        client: AsyncClient,
        test_product: Product,
        test_warehouse: Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.services.alert.send_low_stock_alert_email.delay", lambda *a, **k: None
        )
        await client.post(
            "/api/v1/inventory",
            json={
                "product_id": str(test_product.id),
                "movement_type": "in",
                "quantity": 10,
                "destination_warehouse_id": str(test_warehouse.id),
            },
        )

        response = await client.get("/api/v1/reports/valuation")

        assert response.status_code == 200
        by_warehouse = response.json()["by_warehouse"]
        valuation = next(
            row for row in by_warehouse if row["warehouse_id"] == str(test_warehouse.id)
        )
        assert Decimal(valuation["total_value"]) == test_product.price * 10

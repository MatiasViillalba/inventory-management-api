"""Business logic for aggregate inventory reports.

ReportService computes reports on demand with database-side
aggregation (COUNT/SUM/GROUP BY) rather than loading every Inventory
row into Python, so report cost stays proportional to the number of
warehouses, not the number of stock records. Reports are read-only and
never mutate state.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.warehouse import Warehouse
from app.schemas.report import (
    InventorySummaryReport,
    InventoryValuationReport,
    WarehouseStockSummary,
    WarehouseValuation,
)


class ReportService:
    """Computes cross-warehouse inventory reports.

    Attributes:
        session: The active async database session.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            session: An active AsyncSession, typically injected via the
                FastAPI dependency chain.
        """
        self.session = session

    async def generate_inventory_summary(self) -> InventorySummaryReport:
        """Compute stock quantity and low-stock figures per warehouse.

        A record counts as low stock once its quantity drops to or
        below its threshold, falling back to the global default
        threshold when no per-record threshold is configured — the
        same rule AlertService applies when raising alerts.

        Returns:
            InventorySummaryReport: Global and per-warehouse stock
            figures, as of now.
        """
        default_threshold = get_settings().low_stock_alert_threshold_default
        threshold = func.coalesce(Inventory.low_stock_threshold, default_threshold)

        statement = (
            select(
                Warehouse.id,
                Warehouse.name,
                func.count(Inventory.id).label("distinct_products"),
                func.coalesce(func.sum(Inventory.quantity), 0).label("total_quantity"),
                func.count(case((Inventory.quantity <= threshold, 1))).label(
                    "low_stock_count"
                ),
                func.count(case((Inventory.quantity == 0, 1))).label(
                    "out_of_stock_count"
                ),
            )
            .select_from(Warehouse)
            .join(Inventory, Inventory.warehouse_id == Warehouse.id, isouter=True)
            .group_by(Warehouse.id, Warehouse.name)
            .order_by(Warehouse.name)
        )
        result = await self.session.execute(statement)
        rows = result.all()

        by_warehouse = [
            WarehouseStockSummary(
                warehouse_id=row.id,
                warehouse_name=row.name,
                distinct_products=row.distinct_products,
                total_quantity=row.total_quantity,
                low_stock_count=row.low_stock_count,
                out_of_stock_count=row.out_of_stock_count,
            )
            for row in rows
        ]

        return InventorySummaryReport(
            generated_at=datetime.now(timezone.utc),
            total_warehouses=len(by_warehouse),
            total_stock_quantity=sum(w.total_quantity for w in by_warehouse),
            low_stock_count=sum(w.low_stock_count for w in by_warehouse),
            out_of_stock_count=sum(w.out_of_stock_count for w in by_warehouse),
            by_warehouse=by_warehouse,
        )

    async def generate_valuation_report(self) -> InventoryValuationReport:
        """Compute stock valuation (quantity * unit price) per warehouse.

        Returns:
            InventoryValuationReport: Global and per-warehouse
            inventory value, as of now.
        """
        value_expr = func.coalesce(
            func.sum(Inventory.quantity * Product.price), Decimal("0")
        )

        statement = (
            select(Warehouse.id, Warehouse.name, value_expr.label("total_value"))
            .select_from(Warehouse)
            .join(Inventory, Inventory.warehouse_id == Warehouse.id, isouter=True)
            .join(Product, Product.id == Inventory.product_id, isouter=True)
            .group_by(Warehouse.id, Warehouse.name)
            .order_by(Warehouse.name)
        )
        result = await self.session.execute(statement)
        rows = result.all()

        by_warehouse = [
            WarehouseValuation(
                warehouse_id=row.id,
                warehouse_name=row.name,
                total_value=row.total_value,
            )
            for row in rows
        ]

        return InventoryValuationReport(
            generated_at=datetime.now(timezone.utc),
            total_value=sum((w.total_value for w in by_warehouse), Decimal("0")),
            by_warehouse=by_warehouse,
        )

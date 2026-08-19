"""Pydantic schemas for aggregate inventory reports.

Reports are computed on demand from current Inventory/Product/Warehouse
data rather than stored, so this module exposes response models only —
there is no create/update payload for a report.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class WarehouseStockSummary(BaseModel):
    """Stock summary for a single warehouse.

    Attributes:
        warehouse_id: The warehouse's UUID.
        warehouse_name: Human-readable warehouse name.
        distinct_products: Number of distinct products with a stock
            record in this warehouse.
        total_quantity: Sum of quantity across all of the warehouse's
            inventory records.
        low_stock_count: Number of inventory records at or below their
            low-stock threshold.
        out_of_stock_count: Number of inventory records at zero
            quantity.
    """

    warehouse_id: uuid.UUID
    warehouse_name: str
    distinct_products: int
    total_quantity: int
    low_stock_count: int
    out_of_stock_count: int


class InventorySummaryReport(BaseModel):
    """Global inventory summary across all warehouses.

    Attributes:
        generated_at: Timestamp when the report was computed.
        total_warehouses: Number of warehouses included in the report.
        total_stock_quantity: Sum of quantity across every inventory
            record.
        low_stock_count: Total number of inventory records at or below
            their low-stock threshold, across all warehouses.
        out_of_stock_count: Total number of inventory records at zero
            quantity, across all warehouses.
        by_warehouse: Per-warehouse breakdown of the same figures.
    """

    generated_at: datetime
    total_warehouses: int
    total_stock_quantity: int
    low_stock_count: int
    out_of_stock_count: int
    by_warehouse: list[WarehouseStockSummary]


class WarehouseValuation(BaseModel):
    """Inventory valuation for a single warehouse.

    Attributes:
        warehouse_id: The warehouse's UUID.
        warehouse_name: Human-readable warehouse name.
        total_value: Sum of quantity * unit price across the
            warehouse's inventory records.
    """

    warehouse_id: uuid.UUID
    warehouse_name: str
    total_value: Decimal


class InventoryValuationReport(BaseModel):
    """Global inventory valuation across all warehouses.

    Attributes:
        generated_at: Timestamp when the report was computed.
        total_value: Sum of quantity * unit price across every
            inventory record in the system.
        by_warehouse: Per-warehouse breakdown of the same figure.
    """

    generated_at: datetime
    total_value: Decimal
    by_warehouse: list[WarehouseValuation]

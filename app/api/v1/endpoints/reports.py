"""Read endpoints for aggregate inventory reports.

Backed by ReportService, which computes figures on demand with
database-side aggregation. Reports are stateless and side-effect free,
so every route here is a GET. Both routes are wrapped with
cache_response: the underlying aggregation is comparatively expensive
and, at a short TTL, slightly stale figures are an acceptable
trade-off for a dashboard-style report.
"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis
from app.core.cache import cache_response
from app.core.session import get_db
from app.schemas.report import InventorySummaryReport, InventoryValuationReport
from app.services.report import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])

_REPORT_CACHE_TTL_SECONDS = 60


@router.get("/inventory-summary", response_model=InventorySummaryReport)
@cache_response(key_prefix="reports:inventory-summary", ttl_seconds=_REPORT_CACHE_TTL_SECONDS)
async def get_inventory_summary(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> InventorySummaryReport:
    """Report current stock quantity and low-stock figures per warehouse.

    Args:
        db: Injected async database session.
        redis: Injected async Redis client, used by cache_response.

    Returns:
        InventorySummaryReport: Global and per-warehouse stock figures.
    """
    service = ReportService(db)
    return await service.generate_inventory_summary()


@router.get("/valuation", response_model=InventoryValuationReport)
@cache_response(key_prefix="reports:valuation", ttl_seconds=_REPORT_CACHE_TTL_SECONDS)
async def get_valuation_report(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> InventoryValuationReport:
    """Report current inventory valuation (quantity * unit price) per warehouse.

    Args:
        db: Injected async database session.
        redis: Injected async Redis client, used by cache_response.

    Returns:
        InventoryValuationReport: Global and per-warehouse inventory value.
    """
    service = ReportService(db)
    return await service.generate_valuation_report()
